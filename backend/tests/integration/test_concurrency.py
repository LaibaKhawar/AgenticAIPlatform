"""Concurrency and failure-isolation behaviour.

These tests exist because of two bugs that the serial in-process executor could
never reproduce, and that only appeared once real Celery workers ran
investigations in parallel:

1. evidence references were allocated by counting a run's existing rows, so two
   concurrent investigations raced to insert the same ``EV-n``;
2. the task-failure handler wrote to the same session the failed handler had
   already poisoned, so recording the failure itself raised and the task stayed
   QUEUED forever — the run hung instead of failing.
"""

from __future__ import annotations

import threading
import uuid
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.db.session import session_scope
from app.models.enums import (
    EvidenceSourceType,
    RunStatus,
    TaskStatus,
    WorkflowType,
)
from app.repositories.investigations import EvidenceRepository
from app.repositories.runs import RunRepository

pytestmark = pytest.mark.integration


def _run(session: Session):
    return RunRepository(session).create_run(
        objective="Investigate churn risk across the customer portfolio.",
        workflow_type=WorkflowType.CHURN_INVESTIGATION,
        workflow_mode="STANDARD",
        created_by="tester",
        metadata={},
    )


# --------------------------------------------------------------------------- #
# Evidence reference allocation
# --------------------------------------------------------------------------- #


def test_references_are_numbered_per_customer(seeded_small: dict, db: Session) -> None:
    """Each account's evidence starts at EV-1, independently of the others."""
    from app.repositories.customers import CustomerRepository

    run = _run(db)
    customers = CustomerRepository(db)
    first = customers.get_by_external_id("CUST-000001")
    second = customers.get_by_external_id("CUST-000002")
    repository = EvidenceRepository(db)

    references: dict[str, list[str]] = {}
    for customer in (first, second):
        collected = []
        for index in range(3):
            record = repository.upsert(
                run_id=run.id,
                customer_id=customer.id,
                source_type=EvidenceSourceType.DOCUMENT_CHUNK,
                source_id=f"chunk:{customer.external_id}:{index}",
                content=f"evidence {index}",
            )
            collected.append(record.reference)
        references[customer.external_id] = collected

    assert references["CUST-000001"] == ["EV-1", "EV-2", "EV-3"]
    assert references["CUST-000002"] == ["EV-1", "EV-2", "EV-3"]


def test_concurrent_investigations_do_not_collide_on_references(
    seeded_small: dict, db: Session
) -> None:
    """The regression test for the reference race.

    Four threads persist evidence for four different customers at the same time,
    each in its own session and transaction — the shape real Celery workers
    produce. With run-scoped numbering this raised a UniqueViolation; with
    customer-scoped numbering it must not.
    """
    from app.core.clock import today
    from app.repositories.customers import CustomerFilter, CustomerRepository

    run = _run(db)
    run_id = run.id
    customer_ids = [
        customer.id
        for customer in CustomerRepository(db).list_customers(
            CustomerFilter(), as_of=today(), limit=4
        )
    ]
    assert len(customer_ids) == 4
    db.commit()

    errors: list[BaseException] = []
    barrier = threading.Barrier(len(customer_ids))

    def worker(customer_id: uuid.UUID) -> None:
        try:
            with session_scope() as session:
                repository = EvidenceRepository(session)
                # Line every thread up so the reads genuinely interleave.
                barrier.wait(timeout=10)
                for signal in ("usage", "support", "billing", "nps", "seats", "adoption"):
                    repository.upsert(
                        run_id=run_id,
                        customer_id=customer_id,
                        source_type=EvidenceSourceType.USAGE_METRIC,
                        source_id=f"signal:{signal}",
                        content=f"{signal} detail",
                    )
        except BaseException as error:
            errors.append(error)

    threads = [threading.Thread(target=worker, args=(customer_id,)) for customer_id in customer_ids]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert errors == [], f"concurrent evidence writes failed: {errors!r}"

    with session_scope() as session:
        repository = EvidenceRepository(session)
        assert repository.count_for_run(run_id) == len(customer_ids) * 6
        for customer_id in customer_ids:
            references = [item.reference for item in repository.list_for_run(run_id, customer_id=customer_id)]
            assert sorted(references) == sorted({f"EV-{index}" for index in range(1, 7)})


def test_evidence_upsert_remains_idempotent_per_customer(seeded_small: dict, db: Session) -> None:
    from app.repositories.customers import CustomerRepository

    run = _run(db)
    customer = CustomerRepository(db).get_by_external_id("CUST-000001")
    repository = EvidenceRepository(db)

    first = repository.upsert(
        run_id=run.id,
        customer_id=customer.id,
        source_type=EvidenceSourceType.USAGE_METRIC,
        source_id="signal:usage",
        content="original",
    )
    again = repository.upsert(
        run_id=run.id,
        customer_id=customer.id,
        source_type=EvidenceSourceType.USAGE_METRIC,
        source_id="signal:usage",
        content="updated",
    )
    assert again.id == first.id
    assert again.reference == first.reference
    assert again.content == "updated"
    assert repository.count_for_run(run.id) == 1


# --------------------------------------------------------------------------- #
# Failure isolation
# --------------------------------------------------------------------------- #


def test_a_database_error_inside_a_stage_still_fails_the_task_cleanly(
    seeded_small: dict, api_client: Any, inline_engine: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The regression test for the poisoned-session bug.

    A stage handler that leaves its transaction unusable must still produce a
    FAILED task and a FAILED run — never a task stuck in QUEUED.
    """
    from sqlalchemy.exc import IntegrityError

    from app.orchestration import stages

    def poison(session: Session, run: Any, task: Any) -> dict[str, Any]:
        """Fail the way a unique violation does: mid-flush, session unusable."""
        raise IntegrityError(
            "INSERT INTO evidence ...", {}, Exception("duplicate key value violates unique constraint")
        )

    monkeypatch.setattr(stages, "verify_claims", poison)

    response = api_client.post(
        "/api/v1/runs",
        json={
            "objective": (
                "Analyze enterprise customers renewing within the next 90 days and identify churn "
                "risk, verifying every conclusion."
            ),
            "max_accounts": 1,
        },
    )
    assert response.status_code == 202
    run_id = uuid.UUID(response.json()["run_id"])

    with session_scope() as session:
        repository = RunRepository(session)
        run = repository.get(run_id)
        assert run is not None
        tasks = {task.task_key: task.status for task in repository.list_tasks(run_id)}

    # The failure was recorded rather than swallowed, and nothing is left queued.
    assert tasks["verify_claims"] == TaskStatus.FAILED.value
    assert run.status == RunStatus.FAILED.value
    assert run.error_message
    assert TaskStatus.QUEUED.value not in tasks.values()
    assert TaskStatus.RUNNING.value not in tasks.values()
