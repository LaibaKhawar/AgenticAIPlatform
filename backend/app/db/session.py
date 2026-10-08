"""Engine and session management.

A single synchronous engine is shared by the API and the Celery workers. Sync
SQLAlchemy keeps one mental model for both (Celery has no event loop) and keeps
transaction boundaries obvious; FastAPI runs `def` endpoints in its threadpool.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.errors import DatabaseTransientError
from app.core.logging import get_logger

logger = get_logger(__name__)

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None

# The URL this process was explicitly configured with, if any.
#
# `get_engine()` prefers this over `settings.database_url` so that disposing the
# engine and rebuilding it cannot silently change which database the process
# talks to. That is not hypothetical: the FastAPI lifespan disposes the engine on
# shutdown, and when the app is embedded in a test client, that shutdown used to
# drop a test-configured engine and have the next call rebuild it against the
# development database — which the test suite then truncated.
_configured_url: str | None = None


def _create_engine(url: str) -> Engine:
    settings = get_settings()
    engine = create_engine(
        url,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_recycle=1800,
        future=True,
        connect_args={"application_name": f"{settings.product_name.lower()}-{settings.app_env}"},
    )

    @event.listens_for(engine, "connect")
    def _set_statement_timeout(dbapi_connection: Any, _record: Any) -> None:
        # Bounds any single query so a pathological plan cannot pin a worker.
        with dbapi_connection.cursor() as cursor:
            cursor.execute(f"SET statement_timeout = {settings.db_statement_timeout_ms}")

    return engine


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = _create_engine(_configured_url or get_settings().database_url)
    return _engine


def active_database_url() -> str:
    """The URL the process will use. Exposed so tests can assert on it."""
    return _configured_url or get_settings().database_url


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _session_factory


def configure_engine(url: str) -> Engine:
    """Pin the process to a specific database (used by the test suite).

    The pin survives :func:`dispose_engine`, so a later rebuild returns to the
    same database rather than falling back to ``settings.database_url``.
    """
    global _engine, _session_factory, _configured_url
    dispose_engine()
    _configured_url = url
    _engine = _create_engine(url)
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def dispose_engine() -> None:
    """Release pooled connections. Keeps the configured URL (see above)."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def reset_engine_configuration() -> None:
    """Drop the engine *and* the pin, returning to ``settings.database_url``."""
    global _configured_url
    dispose_engine()
    _configured_url = None


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope: commit on success, roll back on failure.

    Operational database errors are re-raised as :class:`DatabaseTransientError`
    so the retry policy can distinguish "Postgres blipped" from "the code is
    wrong".
    """
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except (OperationalError, DBAPIError) as error:
        session.rollback()
        if getattr(error, "connection_invalidated", False) or isinstance(error, OperationalError):
            raise DatabaseTransientError(f"database operation failed: {error}") from error
        raise
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    with session_scope() as session:
        yield session


def database_healthy() -> tuple[bool, str]:
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        return True, "ok"
    except Exception as error:
        return False, str(error)[:200]


def pgvector_available() -> bool:
    try:
        with get_engine().connect() as connection:
            return bool(connection.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")).scalar())
    except Exception:
        return False
