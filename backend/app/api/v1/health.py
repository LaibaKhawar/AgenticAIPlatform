"""Health, readiness and liveness endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.core.config import get_settings
from app.db.session import database_healthy, pgvector_available
from app.schemas.api import HealthResponse

router = APIRouter(tags=["health"])


def _redis_status() -> tuple[bool, str]:
    settings = get_settings()
    try:
        import redis

        client = redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)
        client.ping()
        return True, "ok"
    except Exception as error:
        return False, str(error)[:160]


@router.get("/health", response_model=HealthResponse, summary="Full dependency health check")
def health(response: Response) -> HealthResponse:
    settings = get_settings()
    db_ok, db_detail = database_healthy()
    vector_ok = pgvector_available() if db_ok else False
    redis_ok, redis_detail = _redis_status()

    healthy = db_ok and vector_ok and redis_ok
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(
        status="ok" if healthy else "degraded",
        product=settings.product_name,
        version="1.0.0",
        environment=settings.app_env,
        database="ok" if db_ok else f"error: {db_detail}",
        pgvector=vector_ok,
        redis="ok" if redis_ok else f"error: {redis_detail}",
        llm_provider=settings.effective_llm_provider,
        llm_model=settings.llm_model,
        embedding_provider=settings.effective_embedding_provider,
        failure_injection=settings.failure_injection_active,
        checks={
            "database": {"ok": db_ok, "detail": db_detail},
            "pgvector": {"ok": vector_ok},
            "redis": {"ok": redis_ok, "detail": redis_detail},
            "executor": settings.workflow_executor,
        },
    )


@router.get("/health/live", summary="Liveness probe", status_code=200)
def live() -> dict[str, str]:
    """Process is up. Deliberately does not touch the database."""
    return {"status": "alive"}


@router.get("/health/ready", summary="Readiness probe")
def ready(response: Response) -> dict[str, object]:
    """Ready to serve traffic: the database must be reachable."""
    db_ok, detail = database_healthy()
    if not db_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if db_ok else "not_ready", "database": db_ok, "detail": detail}
