"""Celery task definitions.

Thin adapters: parse ids, call the engine, log. All control flow, retry
accounting and state transitions live in the engine so the same behaviour holds
when the inline executor is used in tests.
"""

from __future__ import annotations

import uuid

from app.core.logging import get_logger, log_context
from app.orchestration.engine import WorkflowEngine
from app.orchestration.executor import CeleryExecutor
from app.workers.celery_app import celery_app

logger = get_logger(__name__)

_engine: WorkflowEngine | None = None


def engine() -> WorkflowEngine:
    """A worker always dispatches further work through Celery, never inline."""
    global _engine
    if _engine is None:
        _engine = WorkflowEngine(executor=CeleryExecutor())
    return _engine


@celery_app.task(name="veriflow.start_run", bind=True, max_retries=0)
def start_run_task(self, run_id: str) -> dict[str, str]:
    with log_context(run_id=run_id, celery_task_id=self.request.id):
        logger.info("start_run received")
        try:
            engine().start_run(uuid.UUID(run_id))
        except Exception as error:
            # The engine has already persisted the failure on the run; surfacing
            # it here would only trigger Celery's own retry machinery.
            logger.exception("start_run failed", extra={"error": str(error)})
            raise
        return {"run_id": run_id, "status": "started"}


@celery_app.task(name="veriflow.execute_task", bind=True, max_retries=0)
def execute_run_task(self, run_id: str, task_id: str) -> dict[str, str]:
    with log_context(run_id=run_id, task_id=task_id, celery_task_id=self.request.id):
        logger.info("execute_task received")
        engine().execute_task(uuid.UUID(run_id), uuid.UUID(task_id))
        return {"run_id": run_id, "task_id": task_id, "status": "executed"}


@celery_app.task(name="veriflow.resume_after_approval", bind=True, max_retries=0)
def resume_after_approval_task(self, run_id: str) -> dict[str, str]:
    with log_context(run_id=run_id, celery_task_id=self.request.id):
        logger.info("resume_after_approval received")
        engine().resume_after_approval(uuid.UUID(run_id))
        return {"run_id": run_id, "status": "resumed"}


@celery_app.task(name="veriflow.run_evaluation", bind=True, max_retries=0)
def run_evaluation_task(self, evaluation_id: str) -> dict[str, str]:
    from app.evaluation.runner import execute_evaluation

    with log_context(evaluation_id=evaluation_id, celery_task_id=self.request.id):
        logger.info("run_evaluation received")
        execute_evaluation(uuid.UUID(evaluation_id))
        return {"evaluation_id": evaluation_id, "status": "completed"}
