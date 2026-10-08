"""Migrations, constraints and repository behaviour against real PostgreSQL."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.analytics.risk import RiskLevel
from app.core.clock import today
from app.db.session import get_engine, pgvector_available
from app.models.domain import Customer, Payment, Subscription, SupportTicket
from app.models.enums import (
    AccountTier,
    ActionType,
    ActorType,
    ApprovalStatus,
    AuditEventType,
    ClaimStatus,
    ClaimType,
    CustomerOutcome,
    EvidenceSourceType,
    RunStatus,
    SubscriptionStatus,
    TaskStatus,
    WorkflowType,
)
from app.repositories.customers import CustomerFilter, CustomerRepository
from app.repositories.investigations import (
    ApprovalRepository,
    ClaimRepository,
    EvidenceRepository,
    InvestigationRepository,
    ReportRepository,
)
from app.repositories.runs import RunRepository

pytestmark = pytest.mark.integration


# --------------------------------------------------------------------------- #
# Migrations and schema
# --------------------------------------------------------------------------- #


EXPECTED_TABLES = {
    "customers",
    "subscriptions",
    "product_usage",
    "support_tickets",
    "payments",
    "nps_surveys",
    "customer_documents",
    "document_chunks",
    "customer_outcomes",
    "runs",
    "run_tasks",
    "evidence",
    "claims",
    "claim_evidence",
    "investigations",
    "reports",
    "approvals",
    "audit_events",
    "llm_calls",
    "evaluation_runs",
    "alembic_version",
}


def test_migrations_create_every_expected_table(engine) -> None:
    tables = set(inspect(engine).get_table_names())
    missing = EXPECTED_TABLES - tables
    assert not missing, f"migration did not create: {sorted(missing)}"


def test_pgvector_extension_and_index_exist(engine) -> None:
    assert pgvector_available() is True
    with engine.connect() as connection:
        index = connection.execute(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_document_chunks_embedding_hnsw'")
        ).scalar()
    assert index is not None
    assert "hnsw" in index.lower()
    assert "vector_cosine_ops" in index.lower()


def test_alembic_is_at_head(engine) -> None:
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert version == "0002_scope_evidence_refs"


def test_foreign_keys_cascade_on_customer_delete(db: Session) -> None:
    customer = _customer(db)
    db.add(
        SupportTicket(
            customer_id=customer.id,
            external_ticket_id="TKT-CASCADE-1",
            created_at=datetime.now(tz=UTC),
            category="Reporting",
            priority="NORMAL",
            status="RESOLVED",
            subject="s",
            description="d",
        )
    )
    db.flush()
    db.delete(customer)
    db.flush()
    remaining = db.execute(
        text("SELECT count(*) FROM support_tickets WHERE external_ticket_id = 'TKT-CASCADE-1'")
    ).scalar()
    assert remaining == 0


# --------------------------------------------------------------------------- #
# Constraints
# --------------------------------------------------------------------------- #


def _customer(db: Session, *, external_id: str | None = None, tier: AccountTier = AccountTier.ENTERPRISE) -> Customer:
    customer = Customer(
        external_id=external_id or f"CUST-T-{uuid.uuid4().hex[:8]}",
        company_name="Constraint Test Co",
        industry="Software",
        country="United States",
        company_size="1000+",
        employee_count=1200,
        account_tier=tier.value,
        account_manager="Tester",
    )
    db.add(customer)
    db.flush()
    return customer


def test_duplicate_external_id_is_rejected(db: Session) -> None:
    _customer(db, external_id="CUST-DUP-1")
    with pytest.raises(IntegrityError):
        _customer(db, external_id="CUST-DUP-1")


def test_invalid_account_tier_violates_the_check_constraint(db: Session) -> None:
    db.add(
        Customer(
            external_id="CUST-BAD-TIER",
            company_name="x",
            industry="Software",
            country="US",
            company_size="1000+",
            employee_count=1,
            account_tier="PLATINUM",
            account_manager="t",
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_negative_mrr_is_rejected(db: Session) -> None:
    customer = _customer(db)
    db.add(
        Subscription(
            customer_id=customer.id,
            plan="Enterprise",
            monthly_recurring_revenue=-100,
            annual_contract_value=0,
            contract_start=date(2026, 1, 1),
            contract_end=date(2026, 12, 31),
            renewal_date=date(2026, 12, 31),
            subscription_status=SubscriptionStatus.ACTIVE.value,
            seats_purchased=10,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_contract_end_before_start_is_rejected(db: Session) -> None:
    customer = _customer(db)
    db.add(
        Subscription(
            customer_id=customer.id,
            plan="Enterprise",
            monthly_recurring_revenue=100,
            annual_contract_value=1200,
            contract_start=date(2026, 12, 31),
            contract_end=date(2026, 1, 1),
            renewal_date=date(2026, 1, 1),
            subscription_status=SubscriptionStatus.ACTIVE.value,
            seats_purchased=10,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_csat_outside_the_valid_range_is_rejected(db: Session) -> None:
    customer = _customer(db)
    db.add(
        SupportTicket(
            customer_id=customer.id,
            external_ticket_id="TKT-BAD-CSAT",
            created_at=datetime.now(tz=UTC),
            category="Reporting",
            priority="NORMAL",
            status="RESOLVED",
            csat_score=9.0,
            subject="s",
            description="d",
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_negative_days_overdue_is_rejected(db: Session) -> None:
    customer = _customer(db)
    db.add(
        Payment(
            customer_id=customer.id,
            invoice_date=date(2026, 1, 1),
            amount=100,
            payment_status="PAID",
            days_overdue=-5,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_run_progress_is_constrained(db: Session) -> None:
    from app.models.workflow import Run

    db.add(
        Run(
            objective="o",
            workflow_type=WorkflowType.CHURN_INVESTIGATION.value,
            status=RunStatus.QUEUED.value,
            progress=150,
            created_at=datetime.now(tz=UTC),
            run_metadata={},
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


# --------------------------------------------------------------------------- #
# Customer repository
# --------------------------------------------------------------------------- #


def test_resolve_accepts_both_uuid_and_external_id(seeded_small, db: Session) -> None:
    repository = CustomerRepository(db)
    by_external = repository.resolve("CUST-000001")
    assert by_external is not None
    by_uuid = repository.resolve(str(by_external.id))
    assert by_uuid is not None
    assert by_uuid.id == by_external.id


def test_resolve_returns_none_for_unknown_and_malformed_identifiers(seeded_small, db: Session) -> None:
    repository = CustomerRepository(db)
    assert repository.resolve("CUST-999999") is None
    assert repository.resolve("not-a-uuid-at-all") is None
    assert repository.resolve(str(uuid.uuid4())) is None


def test_list_customers_paginates_without_overlap(seeded_small, db: Session) -> None:
    repository = CustomerRepository(db)
    filters = CustomerFilter()
    total = repository.count(filters, as_of=today())
    assert total == 40

    first = repository.list_customers(filters, as_of=today(), limit=10, offset=0)
    second = repository.list_customers(filters, as_of=today(), limit=10, offset=10)
    assert len(first) == 10
    assert len(second) == 10
    assert {c.id for c in first}.isdisjoint({c.id for c in second})


def test_pagination_past_the_end_returns_empty(seeded_small, db: Session) -> None:
    repository = CustomerRepository(db)
    assert repository.list_customers(CustomerFilter(), as_of=today(), limit=10, offset=1000) == []


def test_tier_filter_narrows_results(seeded_small, db: Session) -> None:
    repository = CustomerRepository(db)
    enterprise = repository.list_customers(
        CustomerFilter(account_tier=AccountTier.ENTERPRISE), as_of=today(), limit=100
    )
    assert enterprise
    assert all(c.account_tier == AccountTier.ENTERPRISE.value for c in enterprise)


def test_search_filter_matches_name_and_external_id(seeded_small, db: Session) -> None:
    repository = CustomerRepository(db)
    by_name = repository.list_customers(CustomerFilter(search="Acme"), as_of=today(), limit=10)
    assert [c.external_id for c in by_name] == ["CUST-000001"]
    by_id = repository.list_customers(CustomerFilter(search="CUST-000001"), as_of=today(), limit=10)
    assert [c.external_id for c in by_id] == ["CUST-000001"]


def test_outcome_filter_selects_historical_accounts(seeded_small, db: Session) -> None:
    repository = CustomerRepository(db)
    churned = repository.list_customers(
        CustomerFilter(outcome=CustomerOutcome.CHURNED), as_of=today(), limit=100
    )
    assert all(c.outcome.outcome == CustomerOutcome.CHURNED.value for c in churned)


def test_find_customers_renewing_within_is_bounded_by_the_window(seeded_small, db: Session) -> None:
    repository = CustomerRepository(db)
    reference = today()
    found = repository.find_customers_renewing_within(days=90, as_of=reference, limit=200)
    for customer in found:
        delta = (customer.subscription.renewal_date - reference).days
        assert 0 <= delta <= 90


def test_renewal_search_excludes_cancelled_subscriptions(seeded_small, db: Session) -> None:
    repository = CustomerRepository(db)
    found = repository.find_customers_renewing_within(days=400, as_of=today(), limit=500)
    assert all(
        c.subscription.subscription_status != SubscriptionStatus.CANCELLED.value for c in found
    )


def test_renewal_search_honours_the_tier_filter(seeded_small, db: Session) -> None:
    repository = CustomerRepository(db)
    found = repository.find_customers_renewing_within(
        days=400, as_of=today(), account_tier=AccountTier.ENTERPRISE, limit=200
    )
    assert all(c.account_tier == AccountTier.ENTERPRISE.value for c in found)


def test_load_bundles_is_batched_not_n_plus_one(seeded_small, db: Session) -> None:
    """Five queries regardless of how many customers are screened."""
    repository = CustomerRepository(db)
    ids = [c.id for c in repository.list_customers(CustomerFilter(), as_of=today(), limit=25)]

    statements: list[str] = []
    from sqlalchemy import event

    def record(_conn, _cursor, statement, _params, _context, _many) -> None:
        if statement.strip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(get_engine(), "before_cursor_execute", record)
    try:
        bundles = repository.load_bundles(ids)
    finally:
        event.remove(get_engine(), "before_cursor_execute", record)

    assert len(bundles) == 25
    assert len(statements) <= 8, f"expected a constant number of queries, saw {len(statements)}"


def test_load_bundles_with_no_ids_returns_empty(db: Session) -> None:
    assert CustomerRepository(db).load_bundles([]) == {}


def test_portfolio_stats_counts_real_rows(seeded_small, db: Session) -> None:
    stats = CustomerRepository(db).portfolio_stats(as_of=today())
    assert stats["total_customers"] == 40
    assert stats["documents"] > 0
    assert stats["document_chunks"] >= stats["documents"]
    assert stats["embedded_chunks"] == stats["document_chunks"]
    assert sum(stats["outcomes"].values()) == 40
    assert stats["total_acv"] > 0


# --------------------------------------------------------------------------- #
# Run repository: state transitions and idempotency
# --------------------------------------------------------------------------- #


def _run(db: Session):
    return RunRepository(db).create_run(
        objective="Investigate churn risk for customers renewing soon.",
        workflow_type=WorkflowType.CHURN_INVESTIGATION,
        workflow_mode="STANDARD",
        created_by="tester",
        metadata={"parameters": {"max_accounts": 2}},
    )


def test_run_is_created_queued_with_metadata(db: Session) -> None:
    run = _run(db)
    assert run.status == RunStatus.QUEUED.value
    assert run.progress == 0
    assert run.run_metadata["parameters"]["max_accounts"] == 2
    assert run.created_at is not None


def test_run_status_transitions_set_their_timestamps(db: Session) -> None:
    repository = RunRepository(db)
    run = _run(db)

    repository.set_status(run, RunStatus.RUNNING, stage="planning", progress=10)
    assert run.started_at is not None
    assert run.progress == 10

    repository.set_status(run, RunStatus.COMPLETED)
    assert run.completed_at is not None
    assert run.progress == 100


def test_failed_run_records_the_error_and_timestamp(db: Session) -> None:
    repository = RunRepository(db)
    run = _run(db)
    repository.set_status(run, RunStatus.FAILED, error_message="planner rejected the objective")
    assert run.failed_at is not None
    assert "planner rejected" in run.error_message


def test_progress_is_clamped(db: Session) -> None:
    repository = RunRepository(db)
    run = _run(db)
    repository.set_status(run, RunStatus.RUNNING, progress=500)
    assert run.progress == 100
    repository.set_status(run, RunStatus.RUNNING, progress=-20)
    assert run.progress == 0


def test_task_claim_is_atomic_and_rejects_a_duplicate_delivery(db: Session) -> None:
    """The guard that makes duplicate Celery deliveries harmless."""
    repository = RunRepository(db)
    run = _run(db)
    task = repository.create_task(
        run_id=run.id,
        task_key="select_candidates",
        agent_type="data",
        description="select",
        stage="candidate_selection",
        dependencies=[],
    )
    assert repository.mark_task_queued(task.id, "token-1") is True
    assert repository.claim_task(task.id) is not None
    # A second delivery of the same task finds nothing to claim.
    assert repository.claim_task(task.id) is None


def test_queuing_an_already_queued_task_is_refused(db: Session) -> None:
    repository = RunRepository(db)
    run = _run(db)
    task = repository.create_task(
        run_id=run.id,
        task_key="screen_risk",
        agent_type="risk",
        description="screen",
        stage="risk_screening",
        dependencies=[],
    )
    assert repository.mark_task_queued(task.id, "a") is True
    assert repository.mark_task_queued(task.id, "b") is False


def test_duplicate_task_key_within_a_run_is_rejected(db: Session) -> None:
    repository = RunRepository(db)
    run = _run(db)
    repository.create_task(
        run_id=run.id, task_key="finalize", agent_type="system", description="f", stage="completion", dependencies=[]
    )
    with pytest.raises(IntegrityError):
        repository.create_task(
            run_id=run.id,
            task_key="finalize",
            agent_type="system",
            description="f",
            stage="completion",
            dependencies=[],
        )


def test_retry_then_success_records_the_retry_count(db: Session) -> None:
    repository = RunRepository(db)
    run = _run(db)
    task = repository.create_task(
        run_id=run.id, task_key="verify_claims", agent_type="verifier", description="v", stage="claim_verification",
        dependencies=[], max_retries=3,
    )
    repository.mark_task_queued(task.id, "t")
    claimed = repository.claim_task(task.id)
    assert claimed is not None

    repository.schedule_retry(claimed, "LLMRateLimitError: 429")
    assert claimed.status == TaskStatus.RETRYING.value
    assert claimed.retry_count == 1
    assert claimed.started_at is None

    reclaimed = repository.claim_task(claimed.id)
    assert reclaimed is not None
    repository.complete_task(reclaimed, {"verified": 3})
    assert reclaimed.status == TaskStatus.COMPLETED.value
    assert reclaimed.retry_count == 1
    assert reclaimed.duration_ms is not None
    assert reclaimed.error_message is None


def test_stale_running_task_is_reclaimed(db: Session) -> None:
    """A worker that died must not strand a run forever."""
    repository = RunRepository(db)
    run = _run(db)
    task = repository.create_task(
        run_id=run.id, task_key="generate_report", agent_type="reporter", description="r",
        stage="report_generation", dependencies=[],
    )
    repository.mark_task_queued(task.id, "t")
    claimed = repository.claim_task(task.id)
    assert claimed is not None
    claimed.started_at = datetime.now(tz=UTC) - timedelta(hours=2)
    db.flush()

    assert repository.reclaim_stale_tasks(timeout_seconds=600) == 1
    db.refresh(claimed)
    assert claimed.status == TaskStatus.RETRYING.value


def test_stale_reclaim_fails_a_task_out_of_retries(db: Session) -> None:
    repository = RunRepository(db)
    run = _run(db)
    task = repository.create_task(
        run_id=run.id, task_key="generate_report", agent_type="reporter", description="r",
        stage="report_generation", dependencies=[], max_retries=0,
    )
    repository.mark_task_queued(task.id, "t")
    claimed = repository.claim_task(task.id)
    assert claimed is not None
    claimed.started_at = datetime.now(tz=UTC) - timedelta(hours=2)
    db.flush()

    repository.reclaim_stale_tasks(timeout_seconds=60)
    db.refresh(claimed)
    assert claimed.status == TaskStatus.FAILED.value


def test_cancellation_marks_pending_tasks_cancelled(db: Session) -> None:
    repository = RunRepository(db)
    run = _run(db)
    repository.create_task(
        run_id=run.id, task_key="select_candidates", agent_type="data", description="s",
        stage="candidate_selection", dependencies=[],
    )
    repository.create_task(
        run_id=run.id, task_key="screen_risk", agent_type="risk", description="s",
        stage="risk_screening", dependencies=["select_candidates"],
    )
    db.commit()

    cancelled = repository.request_cancellation(run.id)
    assert cancelled is not None
    assert cancelled.status == RunStatus.CANCELLED.value
    assert repository.is_cancelled(run.id) is True
    assert all(task.status == TaskStatus.CANCELLED.value for task in repository.list_tasks(run.id))


def test_cancelling_a_completed_run_is_a_no_op(db: Session) -> None:
    repository = RunRepository(db)
    run = _run(db)
    repository.set_status(run, RunStatus.COMPLETED)
    db.commit()
    assert repository.request_cancellation(run.id).status == RunStatus.COMPLETED.value


def test_audit_events_are_ordered_and_carry_their_payload(db: Session) -> None:
    repository = RunRepository(db)
    run = _run(db)
    for index, event_type in enumerate(
        (AuditEventType.RUN_CREATED, AuditEventType.PLAN_CREATED, AuditEventType.TASK_STARTED)
    ):
        repository.record_event(
            run_id=run.id,
            event_type=event_type,
            actor_type=ActorType.SYSTEM,
            actor_id="engine",
            message=f"event {index}",
            payload={"index": index},
        )
    events = repository.list_events(run.id)
    assert [e.event_type for e in events] == [
        AuditEventType.RUN_CREATED.value,
        AuditEventType.PLAN_CREATED.value,
        AuditEventType.TASK_STARTED.value,
    ]
    assert events[2].payload["index"] == 2


def test_llm_usage_aggregates_across_calls(db: Session) -> None:
    repository = RunRepository(db)
    run = _run(db)
    for _ in range(3):
        repository.record_llm_call(
            run_id=run.id, task_key="t", agent="investigator", provider="fake", model="m",
            operation="investigate", prompt_tokens=100, completion_tokens=50, latency_ms=20,
            estimated_cost_usd=0.001, attempts=1, valid_output=True,
        )
    usage = repository.llm_usage_for_run(run.id)
    assert usage["calls"] == 3
    assert usage["total_tokens"] == 450
    assert usage["estimated_cost_usd"] == pytest.approx(0.003)
    assert usage["avg_latency_ms"] == pytest.approx(20.0)


def test_llm_usage_for_a_run_with_no_calls_is_zeroed(db: Session) -> None:
    usage = RunRepository(db).llm_usage_for_run(_run(db).id)
    assert usage["calls"] == 0
    assert usage["total_tokens"] == 0


# --------------------------------------------------------------------------- #
# Evidence, claims, investigations, approvals
# --------------------------------------------------------------------------- #


def test_evidence_upsert_is_idempotent_and_assigns_sequential_references(seeded_small, db: Session) -> None:
    run = _run(db)
    customer = CustomerRepository(db).get_by_external_id("CUST-000001")
    repository = EvidenceRepository(db)

    first = repository.upsert(
        run_id=run.id, customer_id=customer.id, source_type=EvidenceSourceType.DOCUMENT_CHUNK,
        source_id="chunk:1", content="original", relevance_score=0.5,
    )
    second = repository.upsert(
        run_id=run.id, customer_id=customer.id, source_type=EvidenceSourceType.USAGE_METRIC,
        source_id="signal:usage", content="metric", relevance_score=0.9,
    )
    assert (first.reference, second.reference) == ("EV-1", "EV-2")

    # A retried task re-upserts rather than duplicating.
    again = repository.upsert(
        run_id=run.id, customer_id=customer.id, source_type=EvidenceSourceType.DOCUMENT_CHUNK,
        source_id="chunk:1", content="updated", relevance_score=0.7,
    )
    assert again.id == first.id
    assert again.content == "updated"
    assert repository.count_for_run(run.id) == 2


def test_evidence_is_scoped_by_customer(seeded_small, db: Session) -> None:
    run = _run(db)
    repository = CustomerRepository(db)
    a = repository.get_by_external_id("CUST-000001")
    b = repository.get_by_external_id("CUST-000002")
    evidence = EvidenceRepository(db)
    evidence.upsert(run_id=run.id, customer_id=a.id, source_type=EvidenceSourceType.DOCUMENT_CHUNK,
                    source_id="chunk:a", content="a")
    evidence.upsert(run_id=run.id, customer_id=b.id, source_type=EvidenceSourceType.DOCUMENT_CHUNK,
                    source_id="chunk:b", content="b")

    assert [e.source_id for e in evidence.list_for_run(run.id, customer_id=a.id)] == ["chunk:a"]
    assert len(evidence.list_for_run(run.id)) == 2


def test_claim_persists_its_evidence_links(seeded_small, db: Session) -> None:
    run = _run(db)
    customer = CustomerRepository(db).get_by_external_id("CUST-000001")
    evidence_repo = EvidenceRepository(db)
    item = evidence_repo.upsert(
        run_id=run.id, customer_id=customer.id, source_type=EvidenceSourceType.DOCUMENT_CHUNK,
        source_id="chunk:x", content="We are evaluating alternative platforms.",
    )
    claims = ClaimRepository(db)
    claims.upsert(
        run_id=run.id, customer_id=customer.id, claim_key="c1",
        claim_text="The customer is evaluating alternatives.", claim_type=ClaimType.OBSERVED_FACT,
        confidence=0.8, evidence=[item],
    )
    db.commit()

    loaded = claims.list_for_run(run.id)[0]
    assert [e.reference for e in loaded.evidence_items] == [item.reference]
    assert loaded.status == ClaimStatus.PENDING.value


def test_claim_upsert_replaces_rather_than_duplicating(seeded_small, db: Session) -> None:
    run = _run(db)
    customer = CustomerRepository(db).get_by_external_id("CUST-000001")
    claims = ClaimRepository(db)
    for text_value in ("first wording", "second wording"):
        claims.upsert(
            run_id=run.id, customer_id=customer.id, claim_key="same-key",
            claim_text=text_value, claim_type=ClaimType.INFERENCE, confidence=0.5, evidence=[],
        )
    stored = claims.list_for_run(run.id)
    assert len(stored) == 1
    assert stored[0].claim_text == "second wording"


def test_verification_statistics_are_computed_from_rows(seeded_small, db: Session) -> None:
    run = _run(db)
    customer = CustomerRepository(db).get_by_external_id("CUST-000001")
    claims = ClaimRepository(db)
    statuses = [
        ClaimStatus.SUPPORTED, ClaimStatus.SUPPORTED, ClaimStatus.PARTIALLY_SUPPORTED,
        ClaimStatus.UNSUPPORTED, ClaimStatus.CONTRADICTED,
    ]
    for index, status in enumerate(statuses):
        claim = claims.upsert(
            run_id=run.id, customer_id=customer.id, claim_key=f"c{index}",
            claim_text=f"claim {index}", claim_type=ClaimType.INFERENCE, confidence=0.5, evidence=[],
        )
        claims.record_verification(
            claim, status=status, confidence=0.8, reason="r", suggested_revision=None, final_text=None
        )
    stats = claims.verification_stats(run.id)
    assert stats["total"] == 5
    assert stats["supported_pct"] == pytest.approx(40.0)
    assert stats["unsupported_pct"] == pytest.approx(40.0)
    assert stats["partially_supported_pct"] == pytest.approx(20.0)


def test_investigation_upsert_is_unique_per_run_and_customer(seeded_small, db: Session) -> None:
    run = _run(db)
    customer = CustomerRepository(db).get_by_external_id("CUST-000001")
    repository = InvestigationRepository(db)
    for score in (60.0, 72.5):
        repository.upsert(
            run_id=run.id, customer_id=customer.id, risk_score=score, heuristic_risk_score=score,
            risk_level=RiskLevel.HIGH, confidence=0.7, summary="s", risk_factors=[],
            quantitative_signals={}, recommended_actions=[], data_gaps=[],
        )
    stored = repository.list_for_run(run.id)
    assert len(stored) == 1
    assert float(stored[0].risk_score) == pytest.approx(72.5)


def test_investigations_are_returned_ranked_by_risk(seeded_small, db: Session) -> None:
    run = _run(db)
    repository = CustomerRepository(db)
    investigations = InvestigationRepository(db)
    for index, score in enumerate((30.0, 90.0, 60.0)):
        customer = repository.get_by_external_id(f"CUST-{index + 1:06d}")
        investigations.upsert(
            run_id=run.id, customer_id=customer.id, risk_score=score, heuristic_risk_score=score,
            risk_level=RiskLevel.HIGH, confidence=0.5, summary="s", risk_factors=[],
            quantitative_signals={}, recommended_actions=[], data_gaps=[],
        )
    scores = [float(i.risk_score) for i in investigations.list_for_run(run.id)]
    assert scores == sorted(scores, reverse=True)


def test_report_upsert_replaces_the_previous_version(db: Session) -> None:
    run = _run(db)
    repository = ReportRepository(db)
    repository.upsert(run_id=run.id, title="v1", executive_summary="a", report_payload={}, markdown_content="# v1")
    repository.upsert(run_id=run.id, title="v2", executive_summary="b", report_payload={}, markdown_content="# v2")
    assert repository.count() == 1
    assert repository.get(run.id).title == "v2"


def test_approval_request_is_idempotent(seeded_small, db: Session) -> None:
    run = _run(db)
    customer = CustomerRepository(db).get_by_external_id("CUST-000001")
    repository = ApprovalRepository(db)

    first, created_first = repository.request(
        run_id=run.id, customer_id=customer.id, action_type=ActionType.OFFER_DISCOUNT,
        proposed_action="Prepare a retention offer.", reason="sensitive",
        action_payload={}, idempotency_key="key-1",
    )
    second, created_second = repository.request(
        run_id=run.id, customer_id=customer.id, action_type=ActionType.OFFER_DISCOUNT,
        proposed_action="Prepare a retention offer.", reason="sensitive",
        action_payload={}, idempotency_key="key-1",
    )
    assert created_first is True
    assert created_second is False
    assert first.id == second.id
    assert repository.count_approvals(run_id=run.id) == 1


def test_approval_resolution_records_the_reviewer(seeded_small, db: Session) -> None:
    run = _run(db)
    repository = ApprovalRepository(db)
    approval, _ = repository.request(
        run_id=run.id, customer_id=None, action_type=ActionType.SEND_CUSTOMER_EMAIL,
        proposed_action="Email the billing contact.", reason="sensitive",
        action_payload={}, idempotency_key="k",
    )
    assert repository.all_resolved(run.id) is False

    repository.resolve(approval, status=ApprovalStatus.APPROVED, reviewed_by="laiba", comment="go ahead")
    assert approval.status == ApprovalStatus.APPROVED.value
    assert approval.reviewed_by == "laiba"
    assert approval.reviewed_at is not None
    assert repository.all_resolved(run.id) is True


def test_seeding_refreshes_planner_statistics(db: Session) -> None:
    """A seed must leave the planner with usable statistics.

    Without them, the first customer-filtered vector search can be planned
    against an empty table, pick the HNSW index, and have the filter discard
    every candidate — retrieval silently returns nothing. Autoanalyze would
    catch up eventually; a run started right after seeding would not wait.
    """
    from sqlalchemy import text

    from app.seed.generator import seed_database

    db.execute(text("ANALYZE customers"))
    before = db.execute(
        text("SELECT last_analyze FROM pg_stat_user_tables WHERE relname = 'document_chunks'")
    ).scalar()

    seed_database(db, customer_count=20, seed=99, reset=True, batch_size=20)
    db.commit()

    after = db.execute(
        text("SELECT last_analyze FROM pg_stat_user_tables WHERE relname = 'document_chunks'")
    ).scalar()
    assert after is not None, "seeding must ANALYZE document_chunks"
    if before is not None:
        assert after >= before
