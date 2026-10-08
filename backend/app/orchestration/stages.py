"""Stage handlers.

One function per task key. Each handler receives an open session and a claimed
task, does its work, and returns a JSON-serialisable output payload that is
persisted on the task row. Handlers raise:

* a :class:`TransientError` subclass to be retried with backoff,
* a :class:`PermanentError` subclass to fail the task immediately,
* :class:`ApprovalRequiredError` to park the run for a human.

The handlers are also where the fan-out happens: ``screen_risk`` creates one
``investigate:<external_id>`` task per selected account and wires the aggregator
to depend on them, so parallelism is a property of the persisted graph rather
than of a worker's in-memory loop.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.agents import (
    AgentRunContext,
    DataAgent,
    InvestigatorAgent,
    ReporterAgent,
    RetrievalAgent,
    RiskAgent,
    VerifierAgent,
)
from app.agents.reporter import AccountInput
from app.analytics import metrics as M
from app.analytics.risk import RiskAssessment, assess_risk
from app.core.clock import today as clock_today
from app.core.config import get_settings
from app.core.errors import (
    ApprovalRequiredError,
    PermanentError,
    ResourceNotFoundError,
)
from app.core.logging import get_logger
from app.llm.client import CallRecord
from app.models.enums import (
    ActionType,
    ActorType,
    AgentType,
    AuditEventType,
    ClaimStatus,
    ClaimType,
    RiskLevel,
    WorkflowMode,
)
from app.models.workflow import Run, RunTask
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

if TYPE_CHECKING:
    from app.orchestration.engine import WorkflowEngine

logger = get_logger(__name__)

INVESTIGATION_PREFIX = "investigate:"


def run_stage(engine: WorkflowEngine, session: Session, run: Run, task: RunTask) -> dict[str, Any]:
    """Dispatch a claimed task to its handler."""
    engine.ensure_not_cancelled(session, run.id)

    if task.task_key.startswith(INVESTIGATION_PREFIX):
        return investigate_one_account(session, run, task)

    handlers: dict[str, Any] = {
        "select_candidates": select_candidates,
        "screen_risk": screen_risk,
        "investigate_accounts": aggregate_investigations,
        "verify_claims": verify_claims,
        "generate_report": generate_report,
        "request_approvals": request_approvals,
        "finalize": finalize,
    }
    handler = handlers.get(task.task_key)
    if handler is None:
        raise PermanentError(
            f"no executor is registered for task '{task.task_key}'",
            details={"task_key": task.task_key},
        )
    return handler(session, run, task)


def _parameters(run: Run, task: RunTask) -> dict[str, Any]:
    merged = dict((run.run_metadata or {}).get("parameters") or {})
    merged.update((task.input_payload or {}).get("parameters") or {})
    return merged


def _record_llm_call(session: Session, run: Run, task: RunTask, record: CallRecord | None) -> None:
    if record is None:
        return
    RunRepository(session).record_llm_call(
        run_id=run.id,
        task_key=task.task_key,
        agent=record.agent,
        provider=record.provider,
        model=record.model,
        operation=record.operation,
        prompt_tokens=record.prompt_tokens,
        completion_tokens=record.completion_tokens,
        latency_ms=record.latency_ms,
        estimated_cost_usd=record.estimated_cost_usd,
        attempts=record.attempts,
        valid_output=record.valid_output,
    )


# --------------------------------------------------------------------------- #
# 1. Candidate selection
# --------------------------------------------------------------------------- #


def select_candidates(session: Session, run: Run, task: RunTask) -> dict[str, Any]:
    parameters = _parameters(run, task)
    agent = DataAgent()
    context = AgentRunContext(session=session, run_id=run.id, task_key=task.task_key)
    candidate_set = agent.select_candidates(
        context,
        window_days=int(parameters.get("renewal_window_days", 90)),
        account_tier=parameters.get("account_tier"),
        limit=200,
    )
    RunRepository(session).merge_metadata(run, {"candidate_count": len(candidate_set.candidates)})
    if not candidate_set.candidates:
        logger.info(
            "no candidate accounts in window",
            extra={"run_id": str(run.id), "window_days": candidate_set.window_days},
        )
    return candidate_set.as_dict()


# --------------------------------------------------------------------------- #
# 2. Risk screening + fan-out
# --------------------------------------------------------------------------- #


def screen_risk(session: Session, run: Run, task: RunTask) -> dict[str, Any]:
    settings = get_settings()
    parameters = _parameters(run, task)
    repository = RunRepository(session)

    upstream = repository.get_task_by_key(run.id, "select_candidates")
    candidates = ((upstream.output_payload or {}).get("candidates") if upstream else []) or []
    customer_ids = [uuid.UUID(candidate["customer_id"]) for candidate in candidates]

    threshold = float(parameters.get("risk_threshold", settings.risk_investigation_threshold))
    max_accounts = int(parameters.get("max_accounts", 5))

    agent = RiskAgent()
    context = AgentRunContext(session=session, run_id=run.id, task_key=task.task_key)
    result = agent.screen(context, customer_ids=customer_ids, threshold=threshold, max_accounts=max_accounts)

    names = {uuid.UUID(candidate["customer_id"]): candidate["company_name"] for candidate in candidates}
    payload = result.as_dict(company_names=names)

    # Fan out: one task per selected account, plus wire the aggregator to them.
    aggregator = repository.get_task_by_key(run.id, "investigate_accounts")
    child_keys: list[str] = []
    for customer_id in result.selected:
        external_id = next(
            (c["external_id"] for c in candidates if c["customer_id"] == str(customer_id)),
            str(customer_id),
        )
        key = f"{INVESTIGATION_PREFIX}{external_id}"
        child_keys.append(key)
        if repository.get_task_by_key(run.id, key) is not None:
            continue  # idempotent on retry
        assessment = result.assessments[customer_id]
        repository.create_task(
            run_id=run.id,
            task_key=key,
            agent_type=AgentType.INVESTIGATOR.value,
            description=f"Investigate {names.get(customer_id, external_id)} ({external_id}).",
            stage="account_investigations",
            dependencies=["screen_risk"],
            input_payload={
                "customer_id": str(customer_id),
                "external_id": external_id,
                "company_name": names.get(customer_id, ""),
                "heuristic_score": assessment.score,
                "parameters": parameters,
                # A single account's failure must not strand the whole run.
                "tolerate_failure": True,
            },
            max_retries=settings.task_max_retries,
        )

    if aggregator is not None and child_keys:
        repository.extend_task_dependencies(aggregator, child_keys)

    repository.merge_metadata(
        run,
        {
            "screened_count": payload["screened"],
            "selected_count": len(result.selected),
            "risk_threshold": threshold,
            "risk_ranking": payload["ranking"][:20],
        },
    )
    repository.record_event(
        run_id=run.id,
        task_id=task.id,
        event_type=AuditEventType.TASK_COMPLETED,
        actor_type=ActorType.AGENT,
        actor_id=AgentType.RISK.value,
        message=(
            f"Screened {payload['screened']} account(s); {len(result.selected)} crossed the "
            f"risk threshold of {threshold}."
        ),
        payload={"selected": [str(cid) for cid in result.selected], "threshold": threshold},
    )
    return {**payload, "investigation_tasks": child_keys}


# --------------------------------------------------------------------------- #
# 3. Per-account investigation
# --------------------------------------------------------------------------- #


def investigate_one_account(session: Session, run: Run, task: RunTask) -> dict[str, Any]:
    payload = task.input_payload or {}
    customer_id = uuid.UUID(payload["customer_id"])
    parameters = _parameters(run, task)

    customers = CustomerRepository(session)
    bundle = customers.load_bundle(customer_id)
    if bundle is None:
        raise ResourceNotFoundError(f"customer not found: {customer_id}")

    reference_date = clock_today()
    assessment = _assess(bundle, as_of=reference_date)

    context = AgentRunContext(session=session, run_id=run.id, task_key=task.task_key, customer_id=customer_id)

    data_pack = DataAgent().collect_customer_data(context, customer_id=customer_id)
    evidence_set = RetrievalAgent().gather(
        context, customer_id=customer_id, assessment=assessment, objective=run.objective
    )
    # An investigation with no qualitative evidence is a materially weaker
    # result than one with it, so say so explicitly rather than quietly
    # returning a metrics-only investigation that looks the same.
    if not evidence_set.documents():
        data_pack.data_gaps.append(
            "No document evidence was retrieved for this account, so the qualitative picture "
            "(emails, CSM notes, QBRs) is missing and the conclusions rest on metrics alone."
        )

    outcome = InvestigatorAgent().investigate(
        context,
        data_pack=data_pack,
        assessment=assessment,
        evidence=evidence_set,
        objective=run.objective,
    )
    _record_llm_call(session, run, task, outcome.call_record)

    # Persist claims with their evidence links (pending verification).
    evidence_by_reference = EvidenceRepository(session).map_by_reference(run.id, customer_id=customer_id)
    claim_repo = ClaimRepository(session)
    persisted = 0
    for claim in outcome.result.claims:
        linked = [
            evidence_by_reference[reference]
            for reference in claim.evidence_references
            if reference in evidence_by_reference
        ]
        claim_repo.upsert(
            run_id=run.id,
            customer_id=customer_id,
            claim_key=f"{payload['external_id']}::{claim.key}",
            claim_text=claim.text,
            claim_type=ClaimType(claim.claim_type),
            confidence=claim.confidence,
            evidence=linked,
            status=ClaimStatus.PENDING,
        )
        persisted += 1

    investigation = InvestigationRepository(session).upsert(
        run_id=run.id,
        customer_id=customer_id,
        risk_score=outcome.result.risk_score,
        heuristic_risk_score=assessment.score,
        risk_level=RiskLevel(outcome.result.risk_level),
        confidence=outcome.result.confidence,
        summary=outcome.result.summary,
        risk_factors=[factor.model_dump(mode="json") for factor in outcome.result.risk_factors],
        quantitative_signals={
            "assessment": assessment.to_dict(),
            "metrics": {
                "usage": data_pack.usage,
                "support": data_pack.support,
                "payments": data_pack.payments,
                "nps": data_pack.nps,
                "subscription": data_pack.subscription,
            },
        },
        recommended_actions=[action.model_dump(mode="json") for action in outcome.result.recommended_actions],
        data_gaps=outcome.result.data_gaps,
    )

    repository = RunRepository(session)
    repository.record_event(
        run_id=run.id,
        task_id=task.id,
        customer_id=customer_id,
        event_type=AuditEventType.INVESTIGATION_COMPLETED,
        actor_type=ActorType.AGENT,
        actor_id=AgentType.INVESTIGATOR.value,
        message=(
            f"Investigated {payload.get('company_name') or payload['external_id']}: "
            f"risk {outcome.result.risk_score}/100 ({outcome.result.risk_level.value}), "
            f"{persisted} claim(s) from {len(evidence_set.items)} evidence record(s)."
        ),
        payload={
            "risk_score": outcome.result.risk_score,
            "heuristic_score": assessment.score,
            "claims": persisted,
            "evidence": len(evidence_set.items),
            "dropped_claims": outcome.dropped_claims,
            "hallucinated_references": outcome.invalid_references,
            "injection_detections": evidence_set.injection_detections,
        },
    )
    if outcome.had_hallucinated_evidence:
        repository.record_event(
            run_id=run.id,
            task_id=task.id,
            customer_id=customer_id,
            event_type=AuditEventType.VALIDATION_FAILED,
            actor_type=ActorType.SYSTEM,
            actor_id="evidence-validator",
            message=(
                "The investigator cited evidence references that do not exist. They were removed before verification."
            ),
            payload={"invalid_references": outcome.invalid_references},
        )

    return {
        "customer_id": str(customer_id),
        "external_id": payload["external_id"],
        "investigation_id": str(investigation.id),
        "risk_score": float(investigation.risk_score),
        "heuristic_score": assessment.score,
        "risk_level": investigation.risk_level,
        "claims": persisted,
        "evidence": len(evidence_set.items),
        "dropped_claims": outcome.dropped_claims,
        "data_gaps": outcome.result.data_gaps,
        "parameters_used": {"renewal_window_days": parameters.get("renewal_window_days")},
    }


def _assess(bundle: Any, *, as_of: date) -> RiskAssessment:
    windows = M.summarise_usage_windows(bundle.usage, as_of=as_of)
    return assess_risk(
        customer_id=str(bundle.customer.id),
        usage=windows,
        support=M.summarise_support(bundle.tickets, as_of=as_of),
        payments=M.calculate_payment_delinquency(bundle.payments, as_of=as_of),
        nps=M.get_latest_nps(bundle.nps_surveys),
        seats_purchased=bundle.subscription.seats_purchased if bundle.subscription else None,
        renewal_date=bundle.subscription.renewal_date if bundle.subscription else None,
        as_of=as_of,
    )


def aggregate_investigations(session: Session, run: Run, task: RunTask) -> dict[str, Any]:
    """Fan-in: summarise the per-account investigations that succeeded."""
    repository = RunRepository(session)
    children = [child for child in repository.list_tasks(run.id) if child.task_key.startswith(INVESTIGATION_PREFIX)]
    succeeded = [child for child in children if child.status == "COMPLETED"]
    failed = [child for child in children if child.status == "FAILED"]
    investigations = InvestigationRepository(session).list_for_run(run.id)

    if children and not succeeded:
        raise PermanentError(
            "every account investigation failed; there is nothing to verify or report",
            details={"failed_tasks": [child.task_key for child in failed]},
        )

    return {
        "investigated": len(succeeded),
        "failed": len(failed),
        "failed_tasks": [child.task_key for child in failed],
        "persisted_investigations": len(investigations),
        "ranked": [
            {
                "customer_id": str(investigation.customer_id),
                "risk_score": float(investigation.risk_score),
                "risk_level": investigation.risk_level,
            }
            for investigation in investigations
        ],
    }


# --------------------------------------------------------------------------- #
# 4. Verification
# --------------------------------------------------------------------------- #


def verify_claims(session: Session, run: Run, task: RunTask) -> dict[str, Any]:
    claim_repo = ClaimRepository(session)
    claims = claim_repo.list_for_run(run.id)
    if not claims:
        return {"verified": 0, "note": "no material claims were produced"}

    context = AgentRunContext(session=session, run_id=run.id, task_key=task.task_key)
    outcome = VerifierAgent().verify(context, claims=claims, run_id=run.id)
    _record_llm_call(session, run, task, outcome.call_record)

    by_key = {claim.claim_key: claim for claim in claims}
    verdicts = outcome.by_key()
    repository = RunRepository(session)

    for key, verdict in verdicts.items():
        claim = by_key.get(key)
        if claim is None:
            continue
        claim_repo.record_verification(
            claim,
            status=verdict.status,
            confidence=verdict.confidence,
            reason=verdict.reason,
            suggested_revision=verdict.suggested_revision,
            final_text=verdict.final_text,
        )
        repository.record_event(
            run_id=run.id,
            task_id=task.id,
            customer_id=claim.customer_id,
            event_type=AuditEventType.CLAIM_VERIFIED,
            actor_type=ActorType.AGENT,
            actor_id=AgentType.VERIFIER.value,
            message=f"{key}: {verdict.status.value}",
            payload={
                "claim_key": key,
                "status": verdict.status.value,
                "confidence": verdict.confidence,
                "reason": verdict.reason[:1000],
                "decided_by": verdict.decided_by,
                "invalid_references": verdict.invalid_references,
                "suggested_revision": verdict.suggested_revision,
            },
        )

    stats = outcome.stats()
    repository.merge_metadata(run, {"verification": stats})
    logger.info("verification stage complete", extra=stats)
    return {"verified": stats["total"], **stats}


# --------------------------------------------------------------------------- #
# 5. Reporting
# --------------------------------------------------------------------------- #


def generate_report(session: Session, run: Run, task: RunTask) -> dict[str, Any]:
    parameters = _parameters(run, task)
    investigations = InvestigationRepository(session).list_for_run(run.id)
    claim_repo = ClaimRepository(session)
    evidence_repo = EvidenceRepository(session)
    customers = CustomerRepository(session)

    accounts: list[AccountInput] = []
    for investigation in investigations:
        customer = customers.get_with_subscription(investigation.customer_id)
        if customer is None:
            continue
        accounts.append(
            AccountInput(
                investigation=investigation,
                company_name=customer.company_name,
                external_id=customer.external_id,
                renewal_date=customer.subscription.renewal_date if customer.subscription else None,
                monthly_recurring_revenue=(
                    float(customer.subscription.monthly_recurring_revenue) if customer.subscription else None
                ),
                annual_contract_value=(
                    float(customer.subscription.annual_contract_value) if customer.subscription else None
                ),
                claims=claim_repo.list_for_run(run.id, customer_id=investigation.customer_id),
                evidence=evidence_repo.list_for_run(run.id, customer_id=investigation.customer_id),
            )
        )

    verification = claim_repo.verification_stats(run.id)
    stats = {
        "candidates": (run.run_metadata or {}).get("screened_count", 0),
        "investigated": len(accounts),
        "risk_threshold": parameters.get("risk_threshold"),
        "total_claims": verification["total"],
        "supported_claims": verification["counts"].get(ClaimStatus.SUPPORTED.value, 0),
        "rejected_claims": (
            verification["counts"].get(ClaimStatus.UNSUPPORTED.value, 0)
            + verification["counts"].get(ClaimStatus.CONTRADICTED.value, 0)
        ),
        "partially_supported_claims": verification["counts"].get(ClaimStatus.PARTIALLY_SUPPORTED.value, 0),
        "investigated_acv": round(sum(account.annual_contract_value or 0 for account in accounts), 2),
    }

    context = AgentRunContext(session=session, run_id=run.id, task_key=task.task_key)
    bundle = ReporterAgent().compose(
        context, objective=run.objective, accounts=accounts, parameters=parameters, stats=stats
    )
    _record_llm_call(session, run, task, bundle.call_record)

    report = ReportRepository(session).upsert(
        run_id=run.id,
        title=bundle.report.title,
        executive_summary=bundle.report.executive_summary,
        report_payload=bundle.payload,
        markdown_content=bundle.markdown,
    )
    RunRepository(session).record_event(
        run_id=run.id,
        task_id=task.id,
        event_type=AuditEventType.REPORT_GENERATED,
        actor_type=ActorType.AGENT,
        actor_id=AgentType.REPORTER.value,
        message=f"Report generated covering {len(accounts)} account(s).",
        payload={"report_id": str(report.id), "accounts": len(accounts), **stats},
    )
    return {
        "report_id": str(report.id),
        "accounts": len(accounts),
        "markdown_chars": len(bundle.markdown),
        **stats,
    }


# --------------------------------------------------------------------------- #
# 6. Approval policy
# --------------------------------------------------------------------------- #


def request_approvals(session: Session, run: Run, task: RunTask) -> dict[str, Any]:
    """Apply the deterministic sensitive-action policy.

    Raises :class:`ApprovalRequiredError` when anything needs a human, which
    parks the run until every request is resolved.
    """
    mode = WorkflowMode(run.workflow_mode)
    investigations = InvestigationRepository(session).list_for_run(run.id)
    approvals = ApprovalRepository(session)
    repository = RunRepository(session)
    customers = CustomerRepository(session)

    created: list[dict[str, Any]] = []
    auto: list[dict[str, Any]] = []

    for investigation in investigations:
        customer = customers.get(investigation.customer_id)
        company = customer.company_name if customer else str(investigation.customer_id)
        for action in investigation.recommended_actions or []:
            try:
                action_type = ActionType(action["action_type"])
            except (KeyError, ValueError):
                continue
            decision = decide(action_type, workflow_mode=mode)
            if not decision.required:
                auto.append({"customer": company, "action_type": action_type.value})
                continue
            approval, is_new = approvals.request(
                run_id=run.id,
                customer_id=investigation.customer_id,
                action_type=action_type,
                proposed_action=action.get("description", ""),
                reason=decision.reason,
                action_payload={
                    "company_name": company,
                    "rationale": action.get("rationale", ""),
                    "priority": action.get("priority", 3),
                    "risk_score": float(investigation.risk_score),
                    "risk_level": investigation.risk_level,
                },
                idempotency_key=approval_idempotency_key(
                    customer_id=investigation.customer_id,
                    action_type=action_type,
                    description=action.get("description", ""),
                ),
            )
            if is_new:
                created.append(
                    {
                        "approval_id": str(approval.id),
                        "customer": company,
                        "action_type": action_type.value,
                        "proposed_action": approval.proposed_action,
                    }
                )
                repository.record_event(
                    run_id=run.id,
                    task_id=task.id,
                    customer_id=investigation.customer_id,
                    event_type=AuditEventType.APPROVAL_REQUESTED,
                    actor_type=ActorType.SYSTEM,
                    actor_id="approval-policy",
                    message=f"Approval required for {action_type.value} on {company}.",
                    payload={"approval_id": str(approval.id), "reason": decision.reason},
                )

    pending = approvals.pending_for_run(run.id)
    summary = {
        "approvals_created": len(created),
        "approvals_pending": len(pending),
        "auto_approved_actions": len(auto),
        "sensitive_actions": created,
        "internal_actions": auto[:50],
        "workflow_mode": mode.value,
    }

    if pending:
        raise ApprovalRequiredError(
            f"{len(pending)} sensitive action(s) require human approval before this run can "
            "complete. No external action has been taken.",
            details=summary,
        )
    return summary


# --------------------------------------------------------------------------- #
# 7. Finalisation
# --------------------------------------------------------------------------- #


def finalize(session: Session, run: Run, task: RunTask) -> dict[str, Any]:
    repository = RunRepository(session)
    approvals = ApprovalRepository(session)
    investigations = InvestigationRepository(session).list_for_run(run.id)
    report = ReportRepository(session).get(run.id)
    verification = ClaimRepository(session).verification_stats(run.id)
    usage = repository.llm_usage_for_run(run.id)

    decisions = [
        {"action_type": approval.action_type, "status": approval.status}
        for approval in approvals.list_approvals(run_id=run.id, limit=200)
    ]
    repository.merge_metadata(
        run,
        {
            "llm_usage": usage,
            "verification": verification,
            "approval_decisions": decisions,
            "report_id": str(report.id) if report else None,
        },
    )
    return {
        "investigations": len(investigations),
        "report_id": str(report.id) if report else None,
        "approvals": len(decisions),
        "verification": verification,
        "llm_usage": usage,
    }
