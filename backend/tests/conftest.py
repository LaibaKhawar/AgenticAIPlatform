"""Shared test fixtures.

Integration and end-to-end tests run against a **real PostgreSQL with
pgvector** (``TEST_DATABASE_URL``), created by running the real Alembic
migrations — not ``create_all`` — so the migrations themselves are under test.

The LLM is always the deterministic fake provider, so no test needs a paid API
key, and agent behaviour is reproducible.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

BACKEND_ROOT = Path(__file__).resolve().parent.parent

# Force a deterministic, offline configuration before app modules import settings.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("LLM_PROVIDER", "fake")
os.environ.setdefault("EMBEDDING_PROVIDER", "local")
os.environ.setdefault("WORKFLOW_EXECUTOR", "inline")
os.environ.setdefault("FAILURE_INJECTION_ENABLED", "false")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("OTEL_ENABLED", "false")

from app.core.config import get_settings  # noqa: E402
from app.db.session import (  # noqa: E402
    active_database_url,
    configure_engine,
    get_session_factory,
    reset_engine_configuration,
)

TABLES_IN_TRUNCATION_ORDER = (
    "claim_evidence",
    "claims",
    "evidence",
    "investigations",
    "reports",
    "approvals",
    "audit_events",
    "llm_calls",
    "run_tasks",
    "runs",
    "evaluation_runs",
    "document_chunks",
    "customer_documents",
    "nps_surveys",
    "payments",
    "support_tickets",
    "product_usage",
    "customer_outcomes",
    "subscriptions",
    "customers",
)


def _database_exists(admin_url: str, name: str) -> bool:
    from sqlalchemy import create_engine

    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            return bool(
                connection.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}
                ).scalar()
            )
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """Create the test database if needed and migrate it to head."""
    settings = get_settings()
    url = settings.test_database_url

    # Hard guard: the suite truncates every table between tests. Pointing it at
    # the development database would silently destroy a seeded dataset, so a
    # misconfiguration must fail loudly here rather than quietly later.
    if url == settings.database_url:
        pytest.fail(
            "TEST_DATABASE_URL must differ from DATABASE_URL — the test suite truncates "
            f"every table and would destroy the application database ({url})."
        )
    if not url.rsplit("/", 1)[-1].endswith("_test"):
        pytest.fail(
            "TEST_DATABASE_URL must name a database ending in '_test' as a second safety net; "
            f"got {url!r}."
        )
    database_name = url.rsplit("/", 1)[-1]
    admin_url = url.rsplit("/", 1)[0] + "/postgres"

    from sqlalchemy import create_engine

    try:
        if not _database_exists(admin_url, database_name):
            engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
            with engine.connect() as connection:
                connection.execute(text(f'CREATE DATABASE "{database_name}"'))
            engine.dispose()
    except Exception as error:  # pragma: no cover - environment dependent
        pytest.skip(f"PostgreSQL is not reachable for integration tests: {error}")

    # Run the real migrations. This is the migration test.
    # Invoked through sys.executable so the test run never depends on the
    # virtualenv's bin directory being on PATH.
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-x", f"url={url}", "upgrade", "head"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:  # pragma: no cover - surfaced as a hard failure
        pytest.fail(f"alembic upgrade failed:\n{result.stdout}\n{result.stderr}")
    return url


@pytest.fixture(scope="session")
def engine(test_database_url: str) -> Iterator[Any]:
    created = configure_engine(test_database_url)
    yield created
    reset_engine_configuration()


@pytest.fixture(autouse=True)
def clean_database(request: pytest.FixtureRequest) -> Iterator[None]:
    """Truncate between tests so each one starts from a known state."""
    if "engine" not in request.fixturenames and not any(
        marker in request.keywords for marker in ("integration", "e2e", "agents")
    ):
        yield
        return
    request.getfixturevalue("engine")
    _truncate()
    yield


def _truncate() -> None:
    """Empty every table. Refuses to run against anything but the test database.

    This is the last line of defence: TRUNCATE on the wrong database destroys a
    seeded dataset, and the failure mode is silent. Asserting the target here
    turns any future engine-configuration mistake into an immediate, obvious
    test failure.
    """
    from app.db.session import get_engine

    target = active_database_url()
    if not target.rsplit("/", 1)[-1].endswith("_test"):
        raise RuntimeError(
            f"refusing to TRUNCATE {target!r}: the test suite may only touch a *_test database"
        )

    with get_engine().begin() as connection:
        connection.execute(
            text("TRUNCATE " + ", ".join(TABLES_IN_TRUNCATION_ORDER) + " RESTART IDENTITY CASCADE")
        )


@pytest.fixture
def db(engine: Any) -> Iterator[Session]:
    """A session that never auto-commits on teardown.

    Tests that deliberately provoke an ``IntegrityError`` leave the session in a
    rolled-back state, and a commit-on-exit fixture would turn each of those
    into a confusing teardown error. Tests that need their writes visible to
    another connection call ``db.commit()`` explicitly.
    """
    session = get_session_factory()()
    try:
        yield session
    finally:
        try:
            session.rollback()
        finally:
            session.close()


@pytest.fixture
def settings() -> Any:
    return get_settings()


@pytest.fixture
def inline_engine(engine: Any) -> Iterator[Any]:
    """A workflow engine that executes everything in-process."""
    from app.orchestration.engine import WorkflowEngine, set_engine
    from app.orchestration.executor import InlineExecutor

    workflow_engine = WorkflowEngine(executor=InlineExecutor())
    set_engine(workflow_engine)
    yield workflow_engine
    set_engine(None)


@pytest.fixture
def api_client(inline_engine: Any, engine: Any) -> Iterator[Any]:
    """A TestClient over the real application.

    The app's lifespan disposes the engine on shutdown. The engine module keeps
    its configured URL across a dispose (see `configure_engine`), so that no
    longer redirects later tests at the development database — this fixture
    asserts the invariant rather than trusting it.
    """
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as client:
        yield client

    assert active_database_url().endswith("_test"), (
        "application shutdown must not change which database the process uses"
    )


@pytest.fixture
def seeded_small(db: Session) -> dict[str, Any]:
    """A small deterministic dataset including the pinned demo account."""
    from app.seed.generator import seed_database

    stats = seed_database(db, customer_count=40, seed=424242, reset=True, batch_size=40)
    db.commit()
    return stats.as_dict()


@pytest.fixture
def demo_customer(seeded_small: dict[str, Any], db: Session) -> Any:
    from app.repositories.customers import CustomerRepository

    customer = CustomerRepository(db).get_by_external_id("CUST-000001")
    assert customer is not None, "the seed must always create the pinned demo account"
    return customer


# --------------------------------------------------------------------------- #
# Hand-built fixtures for unit tests (no database)
# --------------------------------------------------------------------------- #


class Row:
    """Lightweight stand-in for an ORM row in pure-unit tests."""

    def __init__(self, **fields: Any) -> None:
        for key, value in fields.items():
            setattr(self, key, value)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Row({self.__dict__})"


def usage_row(
    *,
    days_ago: int,
    active_users: int,
    sessions: int | None = None,
    api_calls: int = 100,
    adoption: float = 60.0,
    seats_active: int | None = None,
    as_of: date | None = None,
) -> Row:
    reference = as_of or date(2026, 6, 1)
    return Row(
        usage_date=reference - timedelta(days=days_ago),
        active_users=active_users,
        sessions=sessions if sessions is not None else active_users * 3,
        total_logins=active_users * 4,
        api_calls=api_calls,
        projects_created=2,
        feature_adoption_score=adoption,
        seats_active=seats_active if seats_active is not None else active_users,
    )


def ticket_row(
    *,
    days_ago: int,
    priority: str = "NORMAL",
    status: str = "RESOLVED",
    csat: float | None = 4.0,
    resolution_hours: float | None = 8.0,
    as_of: date | None = None,
    subject: str = "Example ticket",
) -> Row:
    reference = as_of or date(2026, 6, 1)
    created = datetime.combine(reference - timedelta(days=days_ago), datetime.min.time(), tzinfo=UTC)
    return Row(
        id=uuid.uuid4(),
        created_at=created,
        resolved_at=created + timedelta(hours=resolution_hours) if resolution_hours else None,
        priority=priority,
        status=status,
        csat_score=csat,
        resolution_hours=resolution_hours,
        subject=subject,
        category="Reporting",
    )


def payment_row(
    *,
    days_ago: int,
    amount: float = 1000.0,
    payment_status: str = "PAID",
    days_overdue: int = 0,
    due_date_offset: int | None = 30,
    paid: bool = True,
    as_of: date | None = None,
) -> Row:
    reference = as_of or date(2026, 6, 1)
    invoice_date = reference - timedelta(days=days_ago)
    return Row(
        invoice_date=invoice_date,
        due_date=invoice_date + timedelta(days=due_date_offset) if due_date_offset is not None else None,
        amount=amount,
        payment_date=invoice_date + timedelta(days=5) if paid else None,
        payment_status=payment_status,
        days_overdue=days_overdue,
    )


def nps_row(*, days_ago: int, score: int, feedback: str = "", as_of: date | None = None) -> Row:
    reference = as_of or date(2026, 6, 1)
    return Row(response_date=reference - timedelta(days=days_ago), score=score, feedback=feedback)


@pytest.fixture
def as_of() -> date:
    return date(2026, 6, 1)
