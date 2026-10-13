"""What this deployment is actually built from, read live.

Library versions come from the installed distributions of the running
interpreter, not from a requirements file that could drift from what is
deployed. Server versions are asked of the servers themselves. Anything that
cannot be determined is reported as ``None`` rather than guessed, and an
unreachable service is reported as unreachable rather than failing the call.
"""

from __future__ import annotations

import platform
from importlib import metadata
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Distribution names as published on PyPI, keyed by the label the UI shows.
LIBRARIES: dict[str, str] = {
    "fastapi": "fastapi",
    "pydantic": "pydantic",
    "sqlalchemy": "SQLAlchemy",
    "alembic": "alembic",
    "celery": "celery",
    "redis_client": "redis",
    "psycopg": "psycopg",
    "pgvector_client": "pgvector",
    # The LLM provider speaks the OpenAI wire format over httpx; there is no
    # OpenAI SDK dependency, so it is deliberately not probed here.
    "httpx": "httpx",
    "opentelemetry": "opentelemetry-sdk",
    "uvicorn": "uvicorn",
}


def library_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for label, distribution in LIBRARIES.items():
        try:
            versions[label] = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            versions[label] = None
    return versions


def database_versions(session: Session) -> dict[str, Any]:
    """PostgreSQL server and pgvector extension versions, from the server."""
    try:
        server = session.execute(text("SHOW server_version")).scalar()
        extension = session.execute(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")).scalar()
    except Exception as error:  # reported, not raised: this is a status probe
        logger.warning("database version probe failed", extra={"error": str(error)[:200]})
        return {"reachable": False, "postgresql": None, "pgvector": None}
    # `server_version` can carry a distro suffix ("16.4 (Debian 16.4-1.pgdg120+2)").
    postgresql = str(server).split(" ", 1)[0] if server else None
    return {"reachable": True, "postgresql": postgresql, "pgvector": str(extension) if extension else None}


def redis_version() -> dict[str, Any]:
    try:
        import redis

        client = redis.from_url(get_settings().redis_url, socket_connect_timeout=2, socket_timeout=2)
        info = client.info("server")
    except Exception as error:
        logger.warning("redis version probe failed", extra={"error": str(error)[:200]})
        return {"reachable": False, "version": None}
    return {"reachable": True, "version": info.get("redis_version")}


def collect_stack(session: Session) -> dict[str, Any]:
    database = database_versions(session)
    cache = redis_version()
    return {
        "python": platform.python_version(),
        "libraries": library_versions(),
        "services": [
            {"name": "postgresql", "version": database["postgresql"], "reachable": database["reachable"]},
            {"name": "pgvector", "version": database["pgvector"], "reachable": database["reachable"]},
            {"name": "redis", "version": cache["version"], "reachable": cache["reachable"]},
        ],
    }
