"""Run endpoints.

``POST /runs`` persists a QUEUED run, hands it to the executor and returns
immediately — the investigation itself happens on workers.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import DbSession, Pagination, parse_uuid
from app.core.config import get_settings
from app.core.errors import ResourceNotFoundError, UnsupportedObjectiveError
from app.core.logging import get_logger
from app.models.enums import (
    ActionType,
    ApprovalStatus,
    ClaimStatus,
    RiskLevel,
    RunStatus,
    TaskStatus,
)
from app.models.workflow import Approval, Investigation, Run
from app.orchestration.engine import STAGE_PROGRESS, get_engine
from app.policy.approvals import approval_idempotency_key, decide
from app.repositories.customers import CustomerRepository
from app.repositories.investigations import (
    ApprovalRepository,
    ClaimRepository,
    EvidenceRepository,
    InvestigationRepository,
    ReportRepository,
)
from app.repositories.runs import RunRepository
from app.schemas.api import (
    ApprovalResponse,
    AuditEventItem,
    ClaimItemResponse,
    CreateRunRequest,
    CreateRunResponse,
    EvidenceItemResponse,
    InvestigationResponse,
    Page,
    RecommendedActionResponse,
    ReportResponse,
    RunDetailResponse,
    RunListItem,
    RunTaskItem,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/runs", tags=["runs"])

# Stage order shown on the run-detail timeline.
STAGE_SEQUENCE: tuple[tuple[str, str], ...] = (
    ("objective_received", "Objective received"),
    ("planning", "Planning"),
    ("candidate_selection", "Candidate selection"),
    ("risk_screening", "Risk screening"),
    ("account_investigations", "Account investigations"),
    ("claim_verification", "Claim verification"),
    ("report_generation", "Report generation"),
    ("approval", "Approval"),
    ("completion", "Completion"),
)


def _run_item(session: Session, run: Run) -> RunListItem:
    duration = None
    end = run.completed_at or run.failed_at
    if run.started_at is not None and end is not None:
        duration = round((end - run.started_at).total_seconds(), 2)
    investigation_count = int(
        session.scalar(select(func.count()).select_from(Investigation).where(Investigation.run_id == run.id)) or 0
    )
    pending = int(
        session.scalar(
            select(func.count())
            .select_from(Approval)
            .where(Approval.run_id == run.id, Approval.status == ApprovalStatus.PENDING.value)
        )
        or 0
    )
    return RunListItem(
        id=run.id,
        objective=run.objective,
        workflow_type=run.workflow_type,
        workflow_mode=run.workflow_mode,
        status=RunStatus(run.status),
        progress=run.progress,
        current_stage=run.current_stage,
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        failed_at=run.failed_at,
        error_message=run.error_message,
        created_by=run.created_by,
        duration_seconds=duration,
        investigation_count=investigation_count,
        pending_approvals=pending,
    )


def _get_run_or_404(session: Session, run_id: str) -> Run:
    parsed = parse_uuid(run_id, field="run id")
    run = RunRepository(session).get(parsed)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "not_found", "message": f"No run with id {run_id}."}},
        )
    return run


def _approval_item(session: Session, approval: Approval) -> ApprovalResponse:
    company = approval.action_payload.get("company_name", "") if approval.action_payload else ""
    if not company and approval.customer_id:
        customer = CustomerRepository(session).get(approval.customer_id)
        company = customer.company_name if customer else ""
    run = RunRepository(session).get(approval.run_id)
    return ApprovalResponse(
        id=approval.id,
        run_id=approval.run_id,
        customer_id=approval.customer_id,
        company_name=company,
        action_type=ActionType(approval.action_type),
        proposed_action=approval.proposed_action,
        action_payload=approval.action_payload or {},
        status=ApprovalStatus(approval.status),
        reason=approval.reason,
        requested_at=approval.requested_at,
        reviewed_at=approval.reviewed_at,
        reviewed_by=approval.reviewed_by,
        reviewer_comment=approval.reviewer_comment,
        run_objective=run.objective if run else "",
    )


# --------------------------------------------------------------------------- #
# Create / list / detail
# --------------------------------------------------------------------------- #


@router.post(
    "",
    response_model=CreateRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start an investigation (returns immediately)",
)
def create_run(payload: CreateRunRequest, session: DbSession) -> CreateRunResponse:
    engine = get_engine()
    try:
        run = engine.create_run(
            session,
            objective=payload.objective,
            parameters=payload.parameters(),
            created_by=payload.created_by,
            workflow_type=payload.workflow_type,
        )
    except UnsupportedObjectiveError as error:
        raise HTTPException(status_code=error.http_status, detail=error.to_payload()) from error

    run_id = run.id
    response = CreateRunResponse(
        run_id=run_id,
        status=RunStatus(run.status),
        objective=run.objective,
        created_at=run.created_at,
        workflow_type=run.workflow_type,
        parameters=(run.run_metadata or {}).get("parameters", {}),
        executor=get_settings().workflow_executor,
    )
    # Commit before dispatch so a worker can never pick up a run that is not
    # yet visible to other connections.
    session.commit()
    engine.enqueue(run_id)
    return response


@router.get("", response_model=Page[RunListItem], summary="List runs")
def list_runs(
    session: DbSession,
    page: Pagination,
    run_status: Annotated[RunStatus | None, Query(alias="status")] = None,
) -> Page[RunListItem]:
    repository = RunRepository(session)
    runs = repository.list_runs(status=run_status, limit=page.limit, offset=page.offset)
    return Page[RunListItem](
        items=[_run_item(session, run) for run in runs],
        total=repository.count_runs(status=run_status),
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{run_id}", response_model=RunDetailResponse, summary="Run detail with live state")
def get_run(run_id: str, session: DbSession) -> RunDetailResponse:
    run = _get_run_or_404(session, run_id)
    repository = RunRepository(session)
    tasks = repository.list_tasks(run.id)
    events = repository.list_events(run.id, limit=400)
    metadata = run.run_metadata or {}
    investigations = InvestigationRepository(session).list_for_run(run.id)
    approvals = ApprovalRepository(session).list_approvals(run_id=run.id, limit=100)

    customers = CustomerRepository(session)
    summaries = []
    for investigation in investigations:
        customer = customers.get(investigation.customer_id)
        summaries.append(
            {
                "customer_id": str(investigation.customer_id),
                "external_id": customer.external_id if customer else "",
                "company_name": customer.company_name if customer else "",
                "risk_score": float(investigation.risk_score),
                "heuristic_risk_score": float(investigation.heuristic_risk_score),
                "risk_level": investigation.risk_level,
                "confidence": float(investigation.confidence),
                "summary": investigation.summary,
            }
        )

    return RunDetailResponse(
        run=_run_item(session, run),
        parameters=metadata.get("parameters", {}),
        plan=metadata.get("plan"),
        stages=_stage_timeline(run, tasks),
        tasks=[
            RunTaskItem(
                id=task.id,
                task_key=task.task_key,
                agent_type=task.agent_type,
                description=task.description,
                stage=task.stage,
                status=TaskStatus(task.status),
                dependencies=task.dependencies,
                retry_count=task.retry_count,
                max_retries=task.max_retries,
                error_message=task.error_message,
                created_at=task.created_at,
                started_at=task.started_at,
                completed_at=task.completed_at,
                duration_ms=task.duration_ms,
                output_summary=_output_summary(task.output_payload),
            )
            for task in tasks
        ],
        events=[AuditEventItem.model_validate(event) for event in events],
        verification=metadata.get("verification"),
        llm_usage=metadata.get("llm_usage") or repository.llm_usage_for_run(run.id),
        investigation_summaries=summaries,
        approvals=[_approval_item(session, approval) for approval in approvals],
        has_report=ReportRepository(session).get(run.id) is not None,
    )


def _stage_timeline(run: Run, tasks: list[Any]) -> list[dict[str, Any]]:
    """Derive the UI timeline from real task state, not a hard-coded script."""
    by_stage: dict[str, list[Any]] = {}
    for task in tasks:
        by_stage.setdefault(task.stage, []).append(task)

    timeline: list[dict[str, Any]] = []
    for stage_key, label in STAGE_SEQUENCE:
        stage_tasks = by_stage.get(stage_key, [])
        statuses = {task.status for task in stage_tasks}
        if not stage_tasks:
            if stage_key == "objective_received":
                state = "COMPLETED"
            elif stage_key == "planning":
                state = "COMPLETED" if tasks else ("FAILED" if run.status == RunStatus.FAILED.value else "RUNNING")
            elif stage_key == "completion" and run.status == RunStatus.COMPLETED.value:
                state = "COMPLETED"
            else:
                state = "PENDING"
        elif TaskStatus.FAILED.value in statuses and not (
            statuses & {TaskStatus.RUNNING.value, TaskStatus.QUEUED.value, TaskStatus.PENDING.value}
        ):
            state = "FAILED" if statuses == {TaskStatus.FAILED.value} else "PARTIAL"
        elif TaskStatus.WAITING_FOR_APPROVAL.value in statuses:
            state = "WAITING_FOR_APPROVAL"
        elif TaskStatus.RUNNING.value in statuses or TaskStatus.QUEUED.value in statuses:
            state = "RUNNING"
        elif TaskStatus.RETRYING.value in statuses:
            state = "RETRYING"
        elif statuses and statuses <= {
            TaskStatus.COMPLETED.value,
            TaskStatus.SKIPPED.value,
            TaskStatus.FAILED.value,
            TaskStatus.CANCELLED.value,
        }:
            state = (
                "COMPLETED"
                if TaskStatus.COMPLETED.value in statuses
                else ("CANCELLED" if TaskStatus.CANCELLED.value in statuses else "SKIPPED")
            )
        else:
            state = "PENDING"

        durations = [task.duration_ms for task in stage_tasks if task.duration_ms]
        timeline.append(
            {
                "key": stage_key,
                "label": label,
                "status": state,
                "progress_marker": STAGE_PROGRESS.get(stage_key, 0),
                "task_count": len(stage_tasks),
                "tasks": [task.task_key for task in stage_tasks],
                "retry_count": sum(task.retry_count for task in stage_tasks),
                "duration_ms": sum(durations) if durations else None,
                "error": next((task.error_message for task in stage_tasks if task.error_message), None),
            }
        )
    return timeline


def _output_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {}
    summary: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, (int, float, bool)) or value is None:
            summary[key] = value
        elif isinstance(value, str):
            summary[key] = value[:200]
        elif isinstance(value, list):
            summary[f"{key}_count"] = len(value)
    return summary


# --------------------------------------------------------------------------- #
# Control
# --------------------------------------------------------------------------- #


@router.post("/{run_id}/cancel", response_model=RunListItem, summary="Cancel a run")
def cancel_run(run_id: str, session: DbSession) -> RunListItem:
    run = _get_run_or_404(session, run_id)
    if RunStatus(run.status).is_terminal:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "conflict",
                    "message": f"Run is already {run.status} and cannot be cancelled.",
                }
            },
        )
    # The engine opens its own transaction; commit this one first so it sees a
    # consistent view.
    session.commit()
    try:
        get_engine().cancel_run(run.id)
    except ResourceNotFoundError as error:
        raise HTTPException(status_code=404, detail=error.to_payload()) from error
    session.expire_all()
    return _run_item(session, _get_run_or_404(session, run_id))


# --------------------------------------------------------------------------- #
# Sub-resources
# --------------------------------------------------------------------------- #


@router.get("/{run_id}/tasks", response_model=list[RunTaskItem], summary="Run tasks")
def list_tasks(run_id: str, session: DbSession) -> list[RunTaskItem]:
    run = _get_run_or_404(session, run_id)
    return [
        RunTaskItem(
            id=task.id,
            task_key=task.task_key,
            agent_type=task.agent_type,
            description=task.description,
            stage=task.stage,
            status=TaskStatus(task.status),
            dependencies=task.dependencies,
            retry_count=task.retry_count,
            max_retries=task.max_retries,
            error_message=task.error_message,
            created_at=task.created_at,
            started_at=task.started_at,
            completed_at=task.completed_at,
            duration_ms=task.duration_ms,
            output_summary=_output_summary(task.output_payload),
        )
        for task in RunRepository(session).list_tasks(run.id)
    ]


@router.get("/{run_id}/events", response_model=list[AuditEventItem], summary="Audit trail")
def list_events(
    run_id: str, session: DbSession, limit: Annotated[int, Query(ge=1, le=1000)] = 400
) -> list[AuditEventItem]:
    run = _get_run_or_404(session, run_id)
    return [AuditEventItem.model_validate(event) for event in RunRepository(session).list_events(run.id, limit=limit)]


@router.get(
    "/{run_id}/investigations",
    response_model=list[InvestigationResponse],
    summary="Investigation results with claims and evidence",
)
def list_investigations(run_id: str, session: DbSession) -> list[InvestigationResponse]:
    run = _get_run_or_404(session, run_id)
    investigations = InvestigationRepository(session).list_for_run(run.id)
    claim_repo = ClaimRepository(session)
    evidence_repo = EvidenceRepository(session)
    customers = CustomerRepository(session)
    approvals = {
        (approval.customer_id, approval.action_type): approval
        for approval in ApprovalRepository(session).list_approvals(run_id=run.id, limit=200)
    }

    responses: list[InvestigationResponse] = []
    for investigation in investigations:
        customer = customers.get_with_subscription(investigation.customer_id)
        claims = claim_repo.list_for_run(run.id, customer_id=investigation.customer_id)
        evidence = evidence_repo.list_for_run(run.id, customer_id=investigation.customer_id)
        actions: list[RecommendedActionResponse] = []
        for action in investigation.recommended_actions or []:
            try:
                action_type = ActionType(action["action_type"])
            except (KeyError, ValueError):
                continue
            decision = decide(action_type)
            approval = approvals.get((investigation.customer_id, action_type.value))
            actions.append(
                RecommendedActionResponse(
                    action_type=action_type,
                    description=action.get("description", ""),
                    rationale=action.get("rationale", ""),
                    priority=int(action.get("priority", 3)),
                    requires_approval=decision.required,
                    approval_status=approval.status if approval else None,
                )
            )

        responses.append(
            InvestigationResponse(
                id=investigation.id,
                run_id=investigation.run_id,
                customer_id=investigation.customer_id,
                external_id=customer.external_id if customer else "",
                company_name=customer.company_name if customer else "",
                account_tier=customer.account_tier if customer else "",
                renewal_date=(customer.subscription.renewal_date if customer and customer.subscription else None),
                monthly_recurring_revenue=(
                    float(customer.subscription.monthly_recurring_revenue)
                    if customer and customer.subscription
                    else None
                ),
                risk_score=float(investigation.risk_score),
                heuristic_risk_score=float(investigation.heuristic_risk_score),
                risk_level=RiskLevel(investigation.risk_level),
                confidence=float(investigation.confidence),
                summary=investigation.summary,
                risk_factors=investigation.risk_factors or [],
                quantitative_signals=investigation.quantitative_signals or {},
                recommended_actions=actions,
                data_gaps=investigation.data_gaps or [],
                claims=[_claim_item(claim) for claim in claims],
                evidence=[_evidence_item(item) for item in evidence],
                created_at=investigation.created_at,
            )
        )
    return responses


def _claim_item(claim: Any) -> ClaimItemResponse:
    return ClaimItemResponse(
        id=claim.id,
        claim_key=claim.claim_key,
        customer_id=claim.customer_id,
        claim_text=claim.claim_text,
        final_text=claim.final_text,
        claim_type=claim.claim_type,
        status=ClaimStatus(claim.status),
        confidence=float(claim.confidence),
        verification_reason=claim.verification_reason,
        suggested_revision=claim.suggested_revision,
        evidence_references=[item.reference for item in claim.evidence_items],
        verified_at=claim.verified_at,
        created_at=claim.created_at,
    )


def _evidence_item(item: Any) -> EvidenceItemResponse:
    return EvidenceItemResponse(
        id=item.id,
        reference=item.reference,
        customer_id=item.customer_id,
        source_type=item.source_type,
        source_id=item.source_id,
        title=item.title,
        content=item.content,
        source_date=item.source_date,
        relevance_score=float(item.relevance_score) if item.relevance_score is not None else None,
        metadata=item.evidence_metadata or {},
        created_at=item.created_at,
    )


@router.get("/{run_id}/claims", response_model=list[ClaimItemResponse], summary="Claims")
def list_claims(
    run_id: str,
    session: DbSession,
    claim_status: Annotated[ClaimStatus | None, Query(alias="status")] = None,
) -> list[ClaimItemResponse]:
    run = _get_run_or_404(session, run_id)
    claims = ClaimRepository(session).list_for_run(run.id, status=claim_status)
    return [_claim_item(claim) for claim in claims]


@router.get("/{run_id}/evidence", response_model=list[EvidenceItemResponse], summary="Evidence")
def list_evidence(
    run_id: str,
    session: DbSession,
    customer_id: Annotated[str | None, Query()] = None,
) -> list[EvidenceItemResponse]:
    run = _get_run_or_404(session, run_id)
    parsed: uuid.UUID | None = parse_uuid(customer_id, field="customer id") if customer_id else None
    items = EvidenceRepository(session).list_for_run(run.id, customer_id=parsed)
    return [_evidence_item(item) for item in items]


@router.get("/{run_id}/report", response_model=ReportResponse, summary="Final report")
def get_report(run_id: str, session: DbSession) -> ReportResponse:
    run = _get_run_or_404(session, run_id)
    report = ReportRepository(session).get(run.id)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "report_not_ready",
                    "message": (f"This run is {run.status} and has not produced a report yet."),
                    "details": {"run_status": run.status, "current_stage": run.current_stage},
                }
            },
        )
    return ReportResponse.model_validate(report)


@router.get(
    "/{run_id}/report.md",
    response_class=PlainTextResponse,
    summary="Final report as Markdown",
    responses={200: {"content": {"text/markdown": {}}}},
)
def get_report_markdown(run_id: str, session: DbSession) -> PlainTextResponse:
    run = _get_run_or_404(session, run_id)
    report = ReportRepository(session).get(run.id)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": {"code": "report_not_ready", "message": "No report yet."}},
        )
    return PlainTextResponse(
        report.markdown_content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="veriflow-report-{run.id}.md"'},
    )


@router.get("/{run_id}/approvals", response_model=list[ApprovalResponse], summary="Approvals for a run")
def list_run_approvals(run_id: str, session: DbSession) -> list[ApprovalResponse]:
    run = _get_run_or_404(session, run_id)
    return [
        _approval_item(session, approval)
        for approval in ApprovalRepository(session).list_approvals(run_id=run.id, limit=200)
    ]


__all__ = ["approval_idempotency_key", "router"]
