"""Celery application.

Celery is the *execution mechanism*, not the workflow. It knows how to run two
things — "plan this run" and "execute this task" — and nothing about stages,
dependencies or approvals. Replacing it later (Temporal, SQS, a thread pool)
means writing one more :class:`~app.orchestration.executor.WorkflowExecutor`.
"""

from __future__ import annotations

from celery import Celery
from celery.signals import setup_logging, worker_process_init

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.telemetry import setup_telemetry

logger = get_logger(__name__)
settings = get_settings()

celery_app = Celery(
    "veriflow",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_default_queue=settings.celery_queue,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # The engine owns retries (it persists retry_count and backoff per task), so
    # Celery must not silently retry on its own.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=200,
    broker_connection_retry_on_startup=True,
    result_expires=3600,
    task_time_limit=1800,
    task_soft_time_limit=1500,
)


@setup_logging.connect
def _configure_celery_logging(**_kwargs: object) -> None:
    """Keep Celery on our JSON formatter instead of its own."""
    configure_logging(force=True)


@worker_process_init.connect
def _init_worker(**_kwargs: object) -> None:
    configure_logging()
    setup_telemetry(service_name="veriflow-worker")
    try:
        from opentelemetry.instrumentation.celery import CeleryInstrumentor

        CeleryInstrumentor().instrument()
    except Exception as error:  # pragma: no cover - optional instrumentation
        logger.debug("celery instrumentation unavailable", extra={"error": str(error)})
    logger.info(
        "worker process ready",
        extra={
            "queue": settings.celery_queue,
            "llm_provider": settings.effective_llm_provider,
            "embedding_provider": settings.effective_embedding_provider,
        },
    )
