"""Scripted demo: ``python -m app.demo``.

Submits the canonical objective through the real engine, follows the run to
completion (approving the sensitive actions it raises), and prints what the
platform actually produced. Useful as a smoke test of the whole pipeline
without a browser.
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import session_scope
from app.models.enums import ApprovalStatus, RunStatus
from app.orchestration.engine import get_engine
from app.repositories.investigations import (
    ApprovalRepository,
    ClaimRepository,
    EvidenceRepository,
    InvestigationRepository,
    ReportRepository,
)
from app.repositories.runs import RunRepository

OBJECTIVE = (
    "Analyze enterprise customers renewing within the next 90 days. Identify the five accounts at "
    "highest risk of churn, investigate the reasons behind each account, verify all important "
    "conclusions using evidence, and recommend retention actions."
)


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _status(run_id: uuid.UUID) -> tuple[str, str, int]:
    with session_scope() as session:
        run = RunRepository(session).get(run_id)
        assert run is not None
        return run.status, run.current_stage, run.progress


def _wait(run_id: uuid.UUID, *, timeout: float) -> str:
    """Poll until the run leaves the active states."""
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        status, stage, progress = _status(run_id)
        marker = f"{status}/{stage}/{progress}"
        if marker != last:
            log(f"  {status:<22} {stage:<24} {progress:>3}%")
            last = marker
        if status in {
            RunStatus.COMPLETED.value,
            RunStatus.FAILED.value,
            RunStatus.CANCELLED.value,
            RunStatus.WAITING_FOR_APPROVAL.value,
        }:
            return status
        time.sleep(1.0)
    return _status(run_id)[0]


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Run the Veriflow demo workflow.")
    parser.add_argument("--objective", default=OBJECTIVE)
    parser.add_argument("--max-accounts", type=int, default=5)
    parser.add_argument("--window", type=int, default=90)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--reject", action="store_true", help="reject the approvals instead of approving")
    arguments = parser.parse_args(argv)

    engine = get_engine()
    log(f"Executor: {settings.workflow_executor} · LLM provider: {settings.effective_llm_provider}")

    with session_scope() as session:
        run = engine.create_run(
            session,
            objective=arguments.objective,
            parameters={
                "renewal_window_days": arguments.window,
                "max_accounts": arguments.max_accounts,
            },
            created_by="demo",
        )
        run_id = run.id
        parameters = dict(run.run_metadata.get("parameters", {}))

    log(f"\nRun {run_id}")
    log(f"Resolved parameters: {parameters}")
    log("\nExecuting:")
    engine.enqueue(run_id)

    status = _wait(run_id, timeout=arguments.timeout)

    if status == RunStatus.WAITING_FOR_APPROVAL.value:
        with session_scope() as session:
            repository = ApprovalRepository(session)
            pending = repository.pending_for_run(run_id)
            log(f"\n{len(pending)} sensitive action(s) require approval:")
            for approval in pending:
                company = approval.action_payload.get("company_name", "portfolio")
                log(f"  [{approval.action_type}] {company} — {approval.proposed_action}")
            decision = ApprovalStatus.REJECTED if arguments.reject else ApprovalStatus.APPROVED
            for approval in pending:
                repository.resolve(
                    approval,
                    status=decision,
                    reviewed_by="demo",
                    comment="Decided by the scripted demo.",
                )
        log(f"\n{'Rejecting' if arguments.reject else 'Approving'} every request and resuming:")
        engine.resume_after_approval(run_id)
        status = _wait(run_id, timeout=arguments.timeout)

    _summarise(run_id)
    return 0 if status == RunStatus.COMPLETED.value else 1


def _summarise(run_id: uuid.UUID) -> None:
    with session_scope() as session:
        repository = RunRepository(session)
        run = repository.get(run_id)
        assert run is not None
        investigations = InvestigationRepository(session).list_for_run(run_id)
        claims = ClaimRepository(session).verification_stats(run_id)
        evidence = EvidenceRepository(session).count_for_run(run_id)
        approvals = ApprovalRepository(session).list_approvals(run_id=run_id, limit=200)
        report = ReportRepository(session).get(run_id)
        usage = repository.llm_usage_for_run(run_id)
        tasks = repository.count_tasks_by_status(run_id)

        print()
        print("=" * 78)
        print(f"RUN {run_id}")
        print("=" * 78)
        print(f"status            {run.status}  (stage {run.current_stage}, progress {run.progress}%)")
        if run.error_message:
            print(f"error             {run.error_message}")
        print(f"tasks             {tasks}")
        print(f"investigations    {len(investigations)}")
        print(f"evidence records  {evidence}")
        print(f"claims            {claims['total']} total · {claims['counts']}")
        print(f"                  {claims['supported_pct']}% supported, {claims['unsupported_pct']}% rejected")
        print(f"approvals         {len(approvals)} ({sum(1 for a in approvals if a.status == 'APPROVED')} approved)")
        print(f"llm usage         {usage}")
        print()

        if investigations:
            print("RANKED ACCOUNTS")
            from app.repositories.customers import CustomerRepository

            customers = CustomerRepository(session)
            for index, investigation in enumerate(investigations, start=1):
                customer = customers.get(investigation.customer_id)
                name = customer.company_name if customer else str(investigation.customer_id)
                print(
                    f"  {index}. {name:<32} {float(investigation.risk_score):>6.1f}  "
                    f"{investigation.risk_level:<9} (heuristic {float(investigation.heuristic_risk_score):.1f})"
                )
            print()

        rejected = [
            claim
            for claim in ClaimRepository(session).list_for_run(run_id)
            if claim.status in {"UNSUPPORTED", "CONTRADICTED"}
        ]
        if rejected:
            print("CLAIMS REJECTED BY VERIFICATION (never asserted in the report)")
            for claim in rejected:
                print(f'  [{claim.status}] "{claim.claim_text}"')
                print(f"      reason: {claim.verification_reason}")
            print()

        if report:
            print("REPORT")
            print(f"  {report.title}")
            print()
            for line in report.executive_summary.splitlines():
                print(f"  {line}")
            print()
            print(f"  (full Markdown: {len(report.markdown_content)} characters)")
        print("=" * 78)


if __name__ == "__main__":
    raise SystemExit(main())
