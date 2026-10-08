"""Dashboard, reports and system-information endpoints.

Every number on this dashboard is computed from the database. There are no
placeholder metrics: if nothing has run yet, the counters are zero and the
``null`` percentages tell the UI to render an empty state.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.agents import describe_agents
from app.analytics.risk import formula_documentation
from app.api.deps import DbSession, Pagination
from app.core.clock import today as clock_today
from app.core.config import get_settings
from app.models.enums import ApprovalStatus, ClaimStatus, RiskLevel, RunStatus
from app.models.workflow import Claim, Evidence, Investigation, LlmCall, Run
from app.policy.approvals import sensitive_action_catalogue
from app.repositories.customers import CustomerRepository
from app.repositories.investigations import (
    ApprovalRepository,
    InvestigationRepository,
    ReportRepository,
)
from app.repositories.runs import RunRepository
from app.schemas.api import (
    DashboardResponse,
    Page,
    ReportListItem,
    ReportResponse,
    SystemInfoResponse,
)
from app.tools.registry import REGISTRY

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", response_model=DashboardResponse, summary="Operational dashboard")
def dashboard(session: DbSession) -> DashboardResponse:
    today = clock_today()
    runs = RunRepository(session)
    customers = CustomerRepository(session)
    approvals = ApprovalRepository(session)

    status_counts = dict(session.execute(select(Run.status, func.count()).group_by(Run.status)).all())
    total_runs = sum(int(count) for count in status_counts.values())
    running = (
        int(status_counts.get(RunStatus.RUNNING.value, 0))
        + int(status_counts.get(RunStatus.QUEUED.value, 0))
        + int(status_counts.get(RunStatus.RETRYING.value, 0))
    )
    failed = int(status_counts.get(RunStatus.FAILED.value, 0))

    completed_runs = session.scalars(
        select(Run).where(
            Run.status == RunStatus.COMPLETED.value,
            Run.started_at.isnot(None),
            Run.completed_at.isnot(None),
        )
    )
    durations = [
        (row.completed_at - row.started_at).total_seconds()
        for row in completed_runs
        if row.completed_at is not None and row.started_at is not None
    ]

    claim_counts = dict(session.execute(select(Claim.status, func.count()).group_by(Claim.status)).all())
    total_claims = sum(int(count) for count in claim_counts.values())
    supported = int(claim_counts.get(ClaimStatus.SUPPORTED.value, 0))
    partial = int(claim_counts.get(ClaimStatus.PARTIALLY_SUPPORTED.value, 0))
    unsupported = int(claim_counts.get(ClaimStatus.UNSUPPORTED.value, 0)) + int(
        claim_counts.get(ClaimStatus.CONTRADICTED.value, 0)
    )

    usage_row = session.execute(
        select(
            func.count(),
            func.coalesce(func.sum(LlmCall.prompt_tokens + LlmCall.completion_tokens), 0),
            func.coalesce(func.sum(LlmCall.estimated_cost_usd), 0),
            func.coalesce(func.avg(LlmCall.latency_ms), 0),
        )
    ).one()

    high_risk = int(
        session.scalar(
            select(func.count(func.distinct(Investigation.customer_id))).where(
                Investigation.risk_level.in_([RiskLevel.HIGH.value, RiskLevel.CRITICAL.value])
            )
        )
        or 0
    )

    dataset = customers.portfolio_stats(as_of=today)
    recent_runs = runs.list_runs(limit=8)

    from app.api.v1.runs import _run_item

    high_risk_accounts: list[dict[str, Any]] = []
    for investigation in InvestigationRepository(session).recent_high_risk(limit=8):
        customer = customers.get_with_subscription(investigation.customer_id)
        high_risk_accounts.append(
            {
                "customer_id": str(investigation.customer_id),
                "external_id": customer.external_id if customer else "",
                "company_name": customer.company_name if customer else "",
                "account_tier": customer.account_tier if customer else "",
                "risk_score": float(investigation.risk_score),
                "risk_level": investigation.risk_level,
                "renewal_date": (
                    customer.subscription.renewal_date.isoformat() if customer and customer.subscription else None
                ),
                "monthly_recurring_revenue": (
                    float(customer.subscription.monthly_recurring_revenue)
                    if customer and customer.subscription
                    else None
                ),
                "run_id": str(investigation.run_id),
                "created_at": investigation.created_at.isoformat(),
            }
        )

    return DashboardResponse(
        investigations_completed=int(session.scalar(select(func.count()).select_from(Investigation)) or 0),
        runs_running=running,
        runs_failed=failed,
        runs_total=total_runs,
        pending_approvals=approvals.count_approvals(status=ApprovalStatus.PENDING),
        high_risk_customers=high_risk,
        avg_run_duration_seconds=(round(sum(durations) / len(durations), 2) if durations else None),
        verified_claim_pct=round(supported / total_claims * 100, 2) if total_claims else None,
        unsupported_claim_pct=round(unsupported / total_claims * 100, 2) if total_claims else None,
        partially_supported_claim_pct=(round(partial / total_claims * 100, 2) if total_claims else None),
        total_customers=dataset["total_customers"],
        renewing_within_90_days=dataset["renewing_within_90_days"],
        evidence_records=int(session.scalar(select(func.count()).select_from(Evidence)) or 0),
        embedded_chunks=dataset["embedded_chunks"],
        llm_usage={
            "calls": int(usage_row[0]),
            "total_tokens": int(usage_row[1]),
            "estimated_cost_usd": round(float(usage_row[2]), 6),
            "avg_latency_ms": round(float(usage_row[3]), 1),
            "provider": get_settings().effective_llm_provider,
            "model": get_settings().llm_model,
        },
        recent_runs=[_run_item(session, run) for run in recent_runs],
        high_risk_accounts=high_risk_accounts,
        dataset=dataset,
    )


@router.get("/reports", response_model=Page[ReportListItem], summary="List generated reports")
def list_reports(session: DbSession, page: Pagination) -> Page[ReportListItem]:
    repository = ReportRepository(session)
    runs = RunRepository(session)
    reports = repository.list_reports(limit=page.limit, offset=page.offset)
    items: list[ReportListItem] = []
    for report in reports:
        run = runs.get(report.run_id)
        accounts = (report.report_payload or {}).get("report", {}).get("accounts", [])
        items.append(
            ReportListItem(
                id=report.id,
                run_id=report.run_id,
                title=report.title,
                executive_summary=report.executive_summary,
                created_at=report.created_at,
                account_count=len(accounts),
                objective=run.objective if run else "",
            )
        )
    return Page[ReportListItem](items=items, total=repository.count(), limit=page.limit, offset=page.offset)


@router.get("/reports/{report_id}", response_model=ReportResponse, summary="One report")
def get_report(report_id: str, session: DbSession) -> ReportResponse:
    from app.api.deps import parse_uuid
    from app.models.workflow import Report

    report = session.get(Report, parse_uuid(report_id, field="report id"))
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "not_found", "message": "No such report."}},
        )
    return ReportResponse.model_validate(report)


@router.get("/system", response_model=SystemInfoResponse, summary="System and capability info")
def system_info() -> SystemInfoResponse:
    settings = get_settings()
    return SystemInfoResponse(
        product=settings.product_name,
        tagline=settings.product_tagline,
        environment=settings.app_env,
        workflow_executor=settings.workflow_executor,
        llm_provider=settings.effective_llm_provider,
        llm_model=settings.llm_model,
        embedding_provider=settings.effective_embedding_provider,
        embedding_model=settings.embedding_model,
        tracing_enabled=settings.otel_enabled,
        langfuse_configured=settings.langfuse_configured,
        failure_injection={
            "active": settings.failure_injection_active,
            "llm_failure_rate": settings.llm_failure_rate,
            "vector_failure_rate": settings.vector_failure_rate,
            "api_failure_rate": settings.api_failure_rate,
            "note": "Forced off when APP_ENV=production.",
        },
        limits={
            "max_parallel_investigations": settings.max_parallel_investigations,
            "max_plan_tasks": settings.max_plan_tasks,
            "max_investigation_candidates": settings.max_investigation_candidates,
            "max_tool_calls_per_task": settings.max_tool_calls_per_task,
            "max_retrieval_chunks": settings.max_retrieval_chunks,
            "max_objective_chars": settings.max_objective_chars,
            "task_max_retries": settings.task_max_retries,
            "api_max_page_size": settings.api_max_page_size,
        },
        agents=describe_agents(),
        tools=[
            {
                "name": spec["name"],
                "description": spec["description"],
                "access": spec["access"],
                "read_only": spec["read_only"],
                "requires_approval": spec["requires_approval"],
                "timeout_seconds": spec["timeout_seconds"],
                "max_attempts": spec["max_attempts"],
            }
            for spec in REGISTRY.describe_all()
        ],
        risk_model=formula_documentation(),
        approval_policy=sensitive_action_catalogue(),
    )
