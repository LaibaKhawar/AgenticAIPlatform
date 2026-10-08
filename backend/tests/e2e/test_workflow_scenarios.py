"""End-to-end workflow scenarios A-F.

Every scenario drives the real engine, the real database and the real agents
(with the deterministic provider) through the HTTP API where possible, and
asserts on persisted state — tasks, evidence, claims, verdicts, reports,
approvals and audit events.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.core.config import get_settings
from app.db.session import session_scope
from app.models.enums import (
    ApprovalStatus,
    AuditEventType,
    ClaimStatus,
    RunStatus,
    TaskStatus,
)
from app.repositories.investigations import (
    ApprovalRepository,
    ClaimRepository,
    EvidenceRepository,
    InvestigationRepository,
    ReportRepository,
)
from app.repositories.runs import RunRepository

pytestmark = pytest.mark.e2e

OBJECTIVE = (
    "Analyze enterprise customers renewing within the next 90 days. Identify the five accounts at "
    "highest risk of churn, investigate each one, verify the evidence, and create a report."
)

# The objective above narrows to the ENTERPRISE tier, which in the 40-customer
# test seed is essentially just the pinned demo account. Tests that need a real
# multi-account fan-out use this wider objective instead.
WIDE_OBJECTIVE = (
    "Analyze all customer accounts renewing within the next 365 days. Identify the accounts at "
    "highest risk of churn, investigate each one, verify the evidence, and create a report."
)


def _create_run(api_client: Any, **overrides: Any) -> uuid.UUID:
    payload = {"objective": OBJECTIVE, "max_accounts": 3, **overrides}
    response = api_client.post("/api/v1/runs", json=payload)
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "QUEUED", "the HTTP request must not wait for execution"
    return uuid.UUID(body["run_id"])


def _state(run_id: uuid.UUID) -> dict[str, Any]:
    with session_scope() as session:
        repository = RunRepository(session)
        run = repository.get(run_id)
        assert run is not None
        return {
            "status": run.status,
            "stage": run.current_stage,
            "progress": run.progress,
            "error": run.error_message,
            "tasks": {task.task_key: task.status for task in repository.list_tasks(run_id)},
            "retries": {task.task_key: task.retry_count for task in repository.list_tasks(run_id)},
        }


# --------------------------------------------------------------------------- #
# Scenario A — the happy path
# --------------------------------------------------------------------------- #


def test_scenario_a_full_investigation_reaches_approval_then_completes(
    seeded_small: dict, api_client: Any, inline_engine: Any
) -> None:
    run_id = _create_run(api_client)

    # The inline executor runs the whole workflow during enqueue, so by now the
    # run has advanced as far as it can without a human.
    state = _state(run_id)
    assert state["status"] == RunStatus.WAITING_FOR_APPROVAL.value
    assert state["stage"] == "approval"

    with session_scope() as session:
        repository = RunRepository(session)

        # --- plan was persisted -------------------------------------------
        run = repository.get(run_id)
        plan = run.run_metadata["plan"]
        assert plan["tasks"], "the validated plan must be persisted"
        assert run.run_metadata["parameters"]["renewal_window_days"] == 90

        # --- tasks were persisted and executed ----------------------------
        tasks = {task.task_key: task for task in repository.list_tasks(run_id)}
        for key in ("select_candidates", "screen_risk", "investigate_accounts", "verify_claims", "generate_report"):
            assert tasks[key].status == TaskStatus.COMPLETED.value, key
            assert tasks[key].duration_ms is not None
        assert tasks["request_approvals"].status == TaskStatus.WAITING_FOR_APPROVAL.value
        assert tasks["finalize"].status == TaskStatus.PENDING.value

        # --- candidates were selected deterministically -------------------
        candidates = tasks["select_candidates"].output_payload["candidates"]
        assert candidates
        assert all(0 <= c["days_to_renewal"] <= 90 for c in candidates)

        # --- risk screening ranked them -----------------------------------
        screening = tasks["screen_risk"].output_payload
        assert screening["screened"] == len(candidates)
        assert 1 <= len(screening["selected"]) <= 3
        scores = [row["score"] for row in screening["ranking"]]
        assert scores == sorted(scores, reverse=True)

        # --- fan-out happened, one task per account -----------------------
        investigation_tasks = [key for key in tasks if key.startswith("investigate:")]
        assert len(investigation_tasks) == len(screening["selected"])
        assert all(tasks[key].status == TaskStatus.COMPLETED.value for key in investigation_tasks)

        # --- investigations persisted --------------------------------------
        investigations = InvestigationRepository(session).list_for_run(run_id)
        assert len(investigations) == len(screening["selected"])
        for investigation in investigations:
            assert 0 <= float(investigation.risk_score) <= 100
            assert investigation.summary
            assert investigation.quantitative_signals
            assert abs(float(investigation.risk_score) - float(investigation.heuristic_risk_score)) <= 15.0

        # --- evidence exists and is attributable ---------------------------
        evidence = EvidenceRepository(session).list_for_run(run_id)
        assert evidence
        for item in evidence:
            assert item.content
            assert item.customer_id is not None
            assert item.reference.startswith("EV-")

        # --- claims exist, cite evidence, and were verified ----------------
        claims = ClaimRepository(session).list_for_run(run_id)
        assert claims
        valid_references = {item.reference for item in evidence}
        for claim in claims:
            assert claim.status != ClaimStatus.PENDING.value, f"{claim.claim_key} was never verified"
            assert claim.verified_at is not None
            assert claim.verification_reason
            for item in claim.evidence_items:
                assert item.reference in valid_references

        # Something was actually rejected — verification is not a rubber stamp.
        statuses = {claim.status for claim in claims}
        assert ClaimStatus.SUPPORTED.value in statuses
        assert statuses & {
            ClaimStatus.CONTRADICTED.value,
            ClaimStatus.UNSUPPORTED.value,
            ClaimStatus.PARTIALLY_SUPPORTED.value,
        }

        # --- report exists and excludes rejected claims --------------------
        report = ReportRepository(session).get(run_id)
        assert report is not None
        assert report.title
        assert report.executive_summary
        assert report.markdown_content.startswith("#")
        assert report.report_payload["evidence_index"]

        rejected = [
            claim.claim_text
            for claim in claims
            if claim.status in {ClaimStatus.UNSUPPORTED.value, ClaimStatus.CONTRADICTED.value}
        ]
        for section in report.report_payload["report"]["accounts"]:
            for conclusion in section["verified_conclusions"]:
                assert conclusion not in rejected

        # --- approvals were opened by deterministic policy ------------------
        approvals = ApprovalRepository(session).list_approvals(run_id=run_id, limit=100)
        assert approvals
        for approval in approvals:
            assert approval.status == ApprovalStatus.PENDING.value
            assert approval.reason
            assert approval.idempotency_key

        # --- audit trail is correlated and complete -------------------------
        events = repository.list_events(run_id)
        event_types = {event.event_type for event in events}
        assert {
            AuditEventType.RUN_CREATED.value,
            AuditEventType.RUN_STARTED.value,
            AuditEventType.PLAN_CREATED.value,
            AuditEventType.TASK_QUEUED.value,
            AuditEventType.TASK_STARTED.value,
            AuditEventType.TASK_COMPLETED.value,
            AuditEventType.INVESTIGATION_COMPLETED.value,
            AuditEventType.CLAIM_VERIFIED.value,
            AuditEventType.REPORT_GENERATED.value,
            AuditEventType.APPROVAL_REQUESTED.value,
        } <= event_types
        assert all(event.run_id == run_id for event in events)

        # --- token/cost telemetry was recorded ------------------------------
        usage = repository.llm_usage_for_run(run_id)
        assert usage["calls"] > 0
        assert usage["total_tokens"] > 0
        assert usage["estimated_cost_usd"] >= 0

        approval_ids = [str(approval.id) for approval in approvals]

    # --- approve everything, run completes --------------------------------
    for approval_id in approval_ids:
        response = api_client.post(
            f"/api/v1/approvals/{approval_id}/approve",
            json={"reviewed_by": "laiba", "comment": "Go ahead."},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "APPROVED"

    final = _state(run_id)
    assert final["status"] == RunStatus.COMPLETED.value
    assert final["progress"] == 100
    assert final["tasks"]["finalize"] == TaskStatus.COMPLETED.value
    assert final["error"] is None


def test_scenario_a_api_surfaces_the_whole_run(
    seeded_small: dict, api_client: Any, inline_engine: Any
) -> None:
    run_id = _create_run(api_client)

    detail = api_client.get(f"/api/v1/runs/{run_id}").json()
    assert detail["run"]["status"] == "WAITING_FOR_APPROVAL"
    assert detail["plan"]["tasks"]
    assert detail["tasks"]
    assert detail["events"]
    assert detail["has_report"] is True
    assert detail["llm_usage"]["calls"] > 0
    assert detail["investigation_summaries"]

    stages = {stage["key"]: stage["status"] for stage in detail["stages"]}
    assert stages["candidate_selection"] == "COMPLETED"
    assert stages["risk_screening"] == "COMPLETED"
    assert stages["account_investigations"] == "COMPLETED"
    assert stages["claim_verification"] == "COMPLETED"
    assert stages["report_generation"] == "COMPLETED"
    assert stages["approval"] == "WAITING_FOR_APPROVAL"

    investigations = api_client.get(f"/api/v1/runs/{run_id}/investigations").json()
    assert investigations
    first = investigations[0]
    assert first["company_name"]
    assert first["claims"]
    assert first["evidence"]
    assert first["risk_factors"]
    assert any(action["requires_approval"] for action in first["recommended_actions"])
    for item in first["evidence"]:
        assert item["source_type"]
        assert item["content"]

    claims = api_client.get(f"/api/v1/runs/{run_id}/claims").json()
    assert claims
    assert all(claim["status"] != "PENDING" for claim in claims)

    supported = api_client.get(f"/api/v1/runs/{run_id}/claims?status=SUPPORTED").json()
    assert all(claim["status"] == "SUPPORTED" for claim in supported)

    evidence = api_client.get(f"/api/v1/runs/{run_id}/evidence").json()
    assert evidence

    report = api_client.get(f"/api/v1/runs/{run_id}/report").json()
    assert report["markdown_content"]
    assert report["report_payload"]["report"]["accounts"]

    markdown = api_client.get(f"/api/v1/runs/{run_id}/report.md")
    assert markdown.status_code == 200
    assert markdown.text.startswith("#")
    assert "attachment" in markdown.headers["content-disposition"]

    listed = api_client.get("/api/v1/runs").json()
    assert listed["total"] == 1
    assert listed["items"][0]["pending_approvals"] > 0


def test_scenario_a_dashboard_reflects_the_completed_work(
    seeded_small: dict, api_client: Any, inline_engine: Any
) -> None:
    run_id = _create_run(api_client)
    body = api_client.get("/api/v1/dashboard").json()

    assert body["runs_total"] == 1
    assert body["investigations_completed"] > 0
    assert body["pending_approvals"] > 0
    assert body["verified_claim_pct"] is not None
    assert 0 <= body["verified_claim_pct"] <= 100
    assert body["evidence_records"] > 0
    assert body["llm_usage"]["calls"] > 0
    assert body["recent_runs"][0]["id"] == str(run_id)


# --------------------------------------------------------------------------- #
# Scenario B — approval pauses and resumes the workflow
# --------------------------------------------------------------------------- #


def test_scenario_b_sensitive_action_pauses_until_approved(
    seeded_small: dict, api_client: Any, inline_engine: Any
) -> None:
    run_id = _create_run(api_client, max_accounts=1)
    assert _state(run_id)["status"] == RunStatus.WAITING_FOR_APPROVAL.value

    approvals = api_client.get(f"/api/v1/approvals?run_id={run_id}").json()["items"]
    assert approvals
    assert all(approval["action_type"] for approval in approvals)
    assert all(approval["reason"] for approval in approvals)

    # Approving only some of them must NOT resume the run.
    api_client.post(f"/api/v1/approvals/{approvals[0]['id']}/approve", json={"reviewed_by": "laiba"})
    if len(approvals) > 1:
        assert _state(run_id)["status"] == RunStatus.WAITING_FOR_APPROVAL.value

    for approval in approvals[1:]:
        api_client.post(f"/api/v1/approvals/{approval['id']}/approve", json={"reviewed_by": "laiba"})

    final = _state(run_id)
    assert final["status"] == RunStatus.COMPLETED.value
    assert final["tasks"]["finalize"] == TaskStatus.COMPLETED.value

    with session_scope() as session:
        events = {e.event_type for e in RunRepository(session).list_events(run_id)}
        assert AuditEventType.APPROVAL_GRANTED.value in events
        assert AuditEventType.RUN_COMPLETED.value in events


def test_scenario_b_approval_survives_a_restart(
    seeded_small: dict, api_client: Any, inline_engine: Any
) -> None:
    """Approval state lives in PostgreSQL, so a fresh engine can resume it."""
    from app.orchestration.engine import WorkflowEngine, set_engine
    from app.orchestration.executor import InlineExecutor

    run_id = _create_run(api_client, max_accounts=1)
    assert _state(run_id)["status"] == RunStatus.WAITING_FOR_APPROVAL.value

    # Simulate a process restart: brand-new engine, no in-memory state.
    replacement = WorkflowEngine(executor=InlineExecutor())
    set_engine(replacement)

    with session_scope() as session:
        pending = ApprovalRepository(session).pending_for_run(run_id)
        repository = ApprovalRepository(session)
        for approval in pending:
            repository.resolve(
                approval, status=ApprovalStatus.APPROVED, reviewed_by="after-restart", comment=None
            )

    replacement.resume_after_approval(run_id)
    assert _state(run_id)["status"] == RunStatus.COMPLETED.value


def test_scenario_b_double_approval_is_a_conflict(
    seeded_small: dict, api_client: Any, inline_engine: Any
) -> None:
    run_id = _create_run(api_client, max_accounts=1)
    approvals = api_client.get(f"/api/v1/approvals?run_id={run_id}").json()["items"]
    approval_id = approvals[0]["id"]

    assert api_client.post(f"/api/v1/approvals/{approval_id}/approve", json={}).status_code == 200
    repeat = api_client.post(f"/api/v1/approvals/{approval_id}/approve", json={})
    assert repeat.status_code == 409
    assert repeat.json()["error"]["code"] == "already_resolved"


def test_scenario_b_approval_requests_are_not_duplicated(
    seeded_small: dict, api_client: Any, inline_engine: Any
) -> None:
    """Re-running the approval stage must not open a second identical request."""
    from app.orchestration.stages import request_approvals

    run_id = _create_run(api_client, max_accounts=2)
    with session_scope() as session:
        repository = ApprovalRepository(session)
        before = repository.count_approvals(run_id=run_id)
        assert before > 0

        run_repository = RunRepository(session)
        run = run_repository.get(run_id)
        task = run_repository.get_task_by_key(run_id, "request_approvals")
        from app.core.errors import ApprovalRequiredError

        with pytest.raises(ApprovalRequiredError) as error:
            request_approvals(session, run, task)
        assert error.value.details["approvals_created"] == 0
        assert repository.count_approvals(run_id=run_id) == before


# --------------------------------------------------------------------------- #
# Scenario C — rejection
# --------------------------------------------------------------------------- #


def test_scenario_c_rejected_action_still_completes_the_run_without_acting(
    seeded_small: dict, api_client: Any, inline_engine: Any
) -> None:
    """Rejection is a decision, not a failure: the run completes, the action is
    recorded as rejected, and nothing external happened."""
    run_id = _create_run(api_client, max_accounts=1)
    approvals = api_client.get(f"/api/v1/approvals?run_id={run_id}").json()["items"]

    for approval in approvals:
        response = api_client.post(
            f"/api/v1/approvals/{approval['id']}/reject",
            json={"reviewed_by": "laiba", "comment": "Too aggressive for this account."},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "REJECTED"

    final = _state(run_id)
    assert final["status"] == RunStatus.COMPLETED.value
    assert final["error"] is None

    with session_scope() as session:
        stored = ApprovalRepository(session).list_approvals(run_id=run_id, limit=100)
        assert stored
        assert all(a.status == ApprovalStatus.REJECTED.value for a in stored)
        assert all(a.reviewer_comment == "Too aggressive for this account." for a in stored)

        events = {e.event_type for e in RunRepository(session).list_events(run_id)}
        assert AuditEventType.APPROVAL_REJECTED.value in events

        # The report still exists — the investigation was valid, only the
        # proposed action was declined.
        assert ReportRepository(session).get(run_id) is not None

        task = RunRepository(session).get_task_by_key(run_id, "request_approvals")
        decisions = task.output_payload["approval_decisions"]
        assert all(decision["status"] == ApprovalStatus.REJECTED.value for decision in decisions)


def test_scenario_c_mixed_decisions_are_all_recorded(
    seeded_small: dict, api_client: Any, inline_engine: Any
) -> None:
    run_id = _create_run(api_client, max_accounts=2)
    approvals = api_client.get(f"/api/v1/approvals?run_id={run_id}&limit=100").json()["items"]
    if len(approvals) < 2:
        pytest.skip("this run produced only one sensitive action")

    api_client.post(f"/api/v1/approvals/{approvals[0]['id']}/approve", json={"reviewed_by": "a"})
    for approval in approvals[1:]:
        api_client.post(f"/api/v1/approvals/{approval['id']}/reject", json={"reviewed_by": "b"})

    assert _state(run_id)["status"] == RunStatus.COMPLETED.value
    with session_scope() as session:
        statuses = {a.status for a in ApprovalRepository(session).list_approvals(run_id=run_id, limit=100)}
        assert statuses == {ApprovalStatus.APPROVED.value, ApprovalStatus.REJECTED.value}


# --------------------------------------------------------------------------- #
# Scenario D — transient failure and recovery
# --------------------------------------------------------------------------- #


def test_scenario_d_transient_llm_failure_is_retried_and_the_run_recovers(
    seeded_small: dict, api_client: Any, inline_engine: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rate-limited model must cost a retry, not a run."""
    from app.core.errors import LLMRateLimitError
    from app.llm import client as llm_client

    original = llm_client.LLMClient._call_provider
    state = {"failures": 0}

    def flaky(self: Any, request: Any, *, operation: str) -> Any:
        if operation == "investigate" and state["failures"] < 1:
            state["failures"] += 1
            raise LLMRateLimitError("Injected: LLM rate limited (429)")
        return original(self, request, operation=operation)

    monkeypatch.setattr(llm_client.LLMClient, "_call_provider", flaky)

    run_id = _create_run(api_client, max_accounts=1)

    assert state["failures"] == 1, "the fault must actually have fired"
    final = _state(run_id)
    assert final["status"] in {RunStatus.WAITING_FOR_APPROVAL.value, RunStatus.COMPLETED.value}

    investigation_retries = {
        key: count for key, count in final["retries"].items() if key.startswith("investigate:")
    }
    assert any(count >= 1 for count in investigation_retries.values()), (
        f"expected a retry to be recorded, saw {investigation_retries}"
    )
    assert all(
        status == TaskStatus.COMPLETED.value
        for key, status in final["tasks"].items()
        if key.startswith("investigate:")
    )

    with session_scope() as session:
        events = [
            event
            for event in RunRepository(session).list_events(run_id)
            if event.event_type == AuditEventType.TASK_RETRYING.value
        ]
        assert events
        assert events[0].payload["error_type"] == "LLMRateLimitError"
        assert events[0].payload["delay_seconds"] >= 0

        # The work still landed.
        assert InvestigationRepository(session).list_for_run(run_id)


def test_scenario_d_vector_failure_is_retried(
    seeded_small: dict, api_client: Any, inline_engine: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.errors import VectorSearchError
    from app.rag import retrieval

    original = retrieval.SemanticRetriever.search
    state = {"failures": 0}

    def flaky(self: Any, **kwargs: Any) -> Any:
        if state["failures"] < 1:
            state["failures"] += 1
            raise VectorSearchError("Injected: vector search unavailable")
        return original(self, **kwargs)

    monkeypatch.setattr(retrieval.SemanticRetriever, "search", flaky)

    run_id = _create_run(api_client, max_accounts=1)
    assert state["failures"] == 1
    final = _state(run_id)
    assert final["status"] in {RunStatus.WAITING_FOR_APPROVAL.value, RunStatus.COMPLETED.value}
    assert any(count >= 1 for count in final["retries"].values())


# --------------------------------------------------------------------------- #
# Scenario E — permanent failure
# --------------------------------------------------------------------------- #


def test_scenario_e_permanent_failure_ends_the_run_failed_with_a_clear_error(
    seeded_small: dict, api_client: Any, inline_engine: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.errors import StructuredOutputError
    from app.llm import client as llm_client

    original = llm_client.LLMClient._call_provider

    def always_malformed(self: Any, request: Any, *, operation: str) -> Any:
        if operation == "verify":
            raise StructuredOutputError("Injected: the model will not produce valid output")
        return original(self, request, operation=operation)

    monkeypatch.setattr(llm_client.LLMClient, "_call_provider", always_malformed)

    run_id = _create_run(api_client, max_accounts=1)
    final = _state(run_id)

    assert final["status"] == RunStatus.FAILED.value
    assert final["error"]
    assert "verify_claims" in final["error"]
    assert final["tasks"]["verify_claims"] == TaskStatus.FAILED.value
    # A permanent error is not retried.
    assert final["retries"]["verify_claims"] == 0
    # Downstream work is explicitly skipped, never left dangling.
    assert final["tasks"]["generate_report"] == TaskStatus.SKIPPED.value
    assert final["tasks"]["finalize"] == TaskStatus.SKIPPED.value

    with session_scope() as session:
        repository = RunRepository(session)
        events = {event.event_type for event in repository.list_events(run_id)}
        assert AuditEventType.TASK_FAILED.value in events
        assert AuditEventType.RUN_FAILED.value in events
        assert AuditEventType.TASK_SKIPPED.value in events

        # Work completed before the failure is preserved for inspection.
        assert InvestigationRepository(session).list_for_run(run_id)
        assert ReportRepository(session).get(run_id) is None

    detail = api_client.get(f"/api/v1/runs/{run_id}").json()
    assert detail["run"]["status"] == "FAILED"
    assert detail["run"]["error_message"]
    failing = next(stage for stage in detail["stages"] if stage["key"] == "claim_verification")
    assert failing["status"] == "FAILED"
    assert failing["error"]

    report = api_client.get(f"/api/v1/runs/{run_id}/report")
    assert report.status_code == 409


def test_scenario_e_retry_budget_is_exhausted_then_the_task_fails(
    seeded_small: dict, api_client: Any, inline_engine: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A permanently unavailable dependency fails after the budget, not forever."""
    from app.core.errors import LLMServiceError
    from app.llm import client as llm_client

    original = llm_client.LLMClient._call_provider
    attempts = {"n": 0}

    def always_down(self: Any, request: Any, *, operation: str) -> Any:
        if operation == "verify":
            attempts["n"] += 1
            raise LLMServiceError("Injected: provider is down (503)")
        return original(self, request, operation=operation)

    monkeypatch.setattr(llm_client.LLMClient, "_call_provider", always_down)

    run_id = _create_run(api_client, max_accounts=1)
    final = _state(run_id)

    assert final["status"] == RunStatus.FAILED.value
    budget = get_settings().task_max_retries
    assert final["retries"]["verify_claims"] == budget
    assert final["tasks"]["verify_claims"] == TaskStatus.FAILED.value
    assert attempts["n"] > budget, "each retry must actually re-attempt the call"


def test_scenario_e_one_failed_account_does_not_strand_the_run(
    seeded_small: dict, api_client: Any, inline_engine: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A single customer's investigation failing must still produce a report for
    the others."""
    from app.agents import investigator as investigator_module
    from app.core.errors import PermanentError

    original = investigator_module.InvestigatorAgent.investigate
    state = {"calls": 0}

    def fail_the_second(self: Any, context: Any, **kwargs: Any) -> Any:
        state["calls"] += 1
        if state["calls"] == 2:
            raise PermanentError("Injected: this account cannot be investigated")
        return original(self, context, **kwargs)

    monkeypatch.setattr(investigator_module.InvestigatorAgent, "investigate", fail_the_second)

    # A wide objective and low threshold so several accounts are genuinely
    # selected; the point of this test is the fan-out, not the screening.
    run_id = _create_run(api_client, objective=WIDE_OBJECTIVE, max_accounts=3, risk_threshold=5)
    final = _state(run_id)

    investigation_tasks = {k: v for k, v in final["tasks"].items() if k.startswith("investigate:")}
    assert len(investigation_tasks) >= 2, f"precondition: need a real fan-out, got {investigation_tasks}"
    assert TaskStatus.FAILED.value in investigation_tasks.values()
    assert TaskStatus.COMPLETED.value in investigation_tasks.values()

    # The run still got through verification, reporting and approval.
    assert final["tasks"]["investigate_accounts"] == TaskStatus.COMPLETED.value
    assert final["tasks"]["verify_claims"] == TaskStatus.COMPLETED.value
    assert final["tasks"]["generate_report"] == TaskStatus.COMPLETED.value
    assert final["status"] in {RunStatus.WAITING_FOR_APPROVAL.value, RunStatus.COMPLETED.value}

    with session_scope() as session:
        aggregate = RunRepository(session).get_task_by_key(run_id, "investigate_accounts")
        assert aggregate.output_payload["failed"] == 1
        assert aggregate.output_payload["investigated"] >= 1
        assert ReportRepository(session).get(run_id) is not None


def test_scenario_e_every_account_failing_fails_the_run(
    seeded_small: dict, api_client: Any, inline_engine: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.agents import investigator as investigator_module
    from app.core.errors import PermanentError

    monkeypatch.setattr(
        investigator_module.InvestigatorAgent,
        "investigate",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(PermanentError("Injected: total failure")),
    )

    run_id = _create_run(api_client, objective=WIDE_OBJECTIVE, max_accounts=2, risk_threshold=5)
    final = _state(run_id)
    assert final["status"] == RunStatus.FAILED.value
    assert final["error"]
    # Downstream stages are skipped rather than left pending forever.
    assert final["tasks"]["verify_claims"] == TaskStatus.SKIPPED.value
    assert final["tasks"]["generate_report"] == TaskStatus.SKIPPED.value


# --------------------------------------------------------------------------- #
# Scenario F — cancellation
# --------------------------------------------------------------------------- #


def test_scenario_f_cancellation_is_persisted_and_stops_further_work(
    seeded_small: dict, api_client: Any, inline_engine: Any
) -> None:
    run_id = _create_run(api_client, max_accounts=1)
    assert _state(run_id)["status"] == RunStatus.WAITING_FOR_APPROVAL.value

    response = api_client.post(f"/api/v1/runs/{run_id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"

    state = _state(run_id)
    assert state["status"] == RunStatus.CANCELLED.value
    assert state["tasks"]["finalize"] == TaskStatus.CANCELLED.value
    assert state["tasks"]["request_approvals"] == TaskStatus.CANCELLED.value

    with session_scope() as session:
        events = {e.event_type for e in RunRepository(session).list_events(run_id)}
        assert AuditEventType.RUN_CANCELLED.value in events


def test_scenario_f_cancelling_twice_is_a_conflict(
    seeded_small: dict, api_client: Any, inline_engine: Any
) -> None:
    run_id = _create_run(api_client, max_accounts=1)
    assert api_client.post(f"/api/v1/runs/{run_id}/cancel").status_code == 200
    repeat = api_client.post(f"/api/v1/runs/{run_id}/cancel")
    assert repeat.status_code == 409
    assert repeat.json()["error"]["code"] == "conflict"


def test_scenario_f_a_late_worker_result_does_not_resurrect_a_cancelled_run(
    seeded_small: dict, api_client: Any, inline_engine: Any
) -> None:
    """The duplicate/late-delivery case: a task arriving after cancellation is
    dropped, not executed."""
    run_id = _create_run(api_client, max_accounts=1)
    api_client.post(f"/api/v1/runs/{run_id}/cancel")

    with session_scope() as session:
        task = RunRepository(session).get_task_by_key(run_id, "finalize")
        task_id = task.id

    # Deliver the task anyway, exactly as a slow broker would.
    inline_engine.execute_task(run_id, task_id)

    state = _state(run_id)
    assert state["status"] == RunStatus.CANCELLED.value
    assert state["tasks"]["finalize"] == TaskStatus.CANCELLED.value


def test_scenario_f_approving_after_cancellation_is_refused(
    seeded_small: dict, api_client: Any, inline_engine: Any
) -> None:
    run_id = _create_run(api_client, max_accounts=1)
    approvals = api_client.get(f"/api/v1/approvals?run_id={run_id}").json()["items"]
    api_client.post(f"/api/v1/runs/{run_id}/cancel")

    response = api_client.post(f"/api/v1/approvals/{approvals[0]['id']}/approve", json={})
    assert response.status_code == 409
    assert _state(run_id)["status"] == RunStatus.CANCELLED.value


# --------------------------------------------------------------------------- #
# Idempotency and duplicate delivery
# --------------------------------------------------------------------------- #


def test_duplicate_task_delivery_does_not_duplicate_work(
    seeded_small: dict, api_client: Any, inline_engine: Any
) -> None:
    run_id = _create_run(api_client, max_accounts=1)

    with session_scope() as session:
        before_evidence = EvidenceRepository(session).count_for_run(run_id)
        before_claims = len(ClaimRepository(session).list_for_run(run_id))
        task = next(
            task
            for task in RunRepository(session).list_tasks(run_id)
            if task.task_key.startswith("investigate:")
        )
        task_id = task.id

    # Re-deliver a completed task. It must be a no-op.
    inline_engine.execute_task(run_id, task_id)

    with session_scope() as session:
        assert EvidenceRepository(session).count_for_run(run_id) == before_evidence
        assert len(ClaimRepository(session).list_for_run(run_id)) == before_claims


def test_replanning_an_already_planned_run_is_a_no_op(
    seeded_small: dict, api_client: Any, inline_engine: Any
) -> None:
    run_id = _create_run(api_client, max_accounts=1)
    with session_scope() as session:
        before = len(RunRepository(session).list_tasks(run_id))

    inline_engine.start_run(run_id)

    with session_scope() as session:
        assert len(RunRepository(session).list_tasks(run_id)) == before


# --------------------------------------------------------------------------- #
# No-high-risk-accounts path
# --------------------------------------------------------------------------- #


def test_no_account_above_the_threshold_still_produces_a_valid_report(
    seeded_small: dict, api_client: Any, inline_engine: Any
) -> None:
    """The honest-empty-answer requirement."""
    run_id = _create_run(api_client, risk_threshold=99.9, max_accounts=5)
    final = _state(run_id)

    assert final["status"] == RunStatus.COMPLETED.value
    assert final["tasks"]["generate_report"] == TaskStatus.COMPLETED.value

    with session_scope() as session:
        assert InvestigationRepository(session).list_for_run(run_id) == []
        report = ReportRepository(session).get(run_id)
        assert report is not None
        summary = report.executive_summary.lower()
        assert "no account" in summary
        assert report.report_payload["report"]["accounts"] == []
        # Nothing to act on, so nothing was proposed.
        assert ApprovalRepository(session).count_approvals(run_id=run_id) == 0


def test_empty_database_produces_a_valid_no_candidates_report(
    api_client: Any, inline_engine: Any
) -> None:
    """An empty warehouse must not crash a run."""
    run_id = _create_run(api_client)
    final = _state(run_id)

    assert final["status"] == RunStatus.COMPLETED.value
    with session_scope() as session:
        task = RunRepository(session).get_task_by_key(run_id, "select_candidates")
        assert task.output_payload["total"] == 0
        report = ReportRepository(session).get(run_id)
        assert report is not None
        assert "no account" in report.executive_summary.lower()
