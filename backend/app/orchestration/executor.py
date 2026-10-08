"""Execution backends.

The orchestration logic in :mod:`app.orchestration.engine` never imports Celery.
It submits work through this interface, which is why the same engine runs
in-process in the test suite and on distributed workers in production — and why
swapping Celery for Temporal later is an executor implementation, not a rewrite
of the workflow.
"""

from __future__ import annotations

import uuid
from collections import deque
from typing import Protocol

from app.core.logging import get_logger

logger = get_logger(__name__)


class WorkflowExecutor(Protocol):
    name: str

    def submit_task(self, run_id: uuid.UUID, task_id: uuid.UUID, *, delay_seconds: float = 0.0) -> None:
        """Schedule one task for execution."""

    def submit_run_start(self, run_id: uuid.UUID) -> None:
        """Schedule planning + first dispatch for a newly created run."""

    def drain(self) -> None:
        """Run anything queued locally. No-op for distributed executors."""


class InlineExecutor:
    """Runs tasks in the current process through an explicit work queue.

    A queue rather than direct recursion: a fan-out of N investigations would
    otherwise nest N stack frames deep (task → advance → task → …). Used by the
    test suite, by ``WORKFLOW_EXECUTOR=inline``, and as the fallback when no
    broker is reachable.
    """

    name = "inline"

    def __init__(self, engine: object | None = None) -> None:
        self._engine = engine
        self._queue: deque[tuple[str, uuid.UUID, uuid.UUID | None]] = deque()
        self._draining = False

    def bind(self, engine: object) -> None:
        self._engine = engine

    def submit_task(self, run_id: uuid.UUID, task_id: uuid.UUID, *, delay_seconds: float = 0.0) -> None:
        # Backoff delays are not slept in-process: the test suite asserts retry
        # behaviour, not wall-clock timing.
        self._queue.append(("task", run_id, task_id))
        self.drain()

    def submit_run_start(self, run_id: uuid.UUID) -> None:
        self._queue.append(("start", run_id, None))
        self.drain()

    def drain(self) -> None:
        if self._draining:
            return
        if self._engine is None:
            raise RuntimeError("InlineExecutor has no engine bound")
        self._draining = True
        try:
            while self._queue:
                kind, run_id, task_id = self._queue.popleft()
                if kind == "start":
                    self._engine.start_run(run_id)  # type: ignore[attr-defined]
                else:
                    assert task_id is not None
                    self._engine.execute_task(run_id, task_id)  # type: ignore[attr-defined]
        finally:
            self._draining = False

    @property
    def pending(self) -> int:
        return len(self._queue)


class CeleryExecutor:
    """Dispatches work onto the Celery queue."""

    name = "celery"

    def submit_task(self, run_id: uuid.UUID, task_id: uuid.UUID, *, delay_seconds: float = 0.0) -> None:
        from app.workers.tasks import execute_run_task

        execute_run_task.apply_async(
            args=[str(run_id), str(task_id)],
            countdown=max(0.0, delay_seconds),
        )
        logger.info(
            "task dispatched to celery",
            extra={"run_id": str(run_id), "task_id": str(task_id), "delay_seconds": delay_seconds},
        )

    def submit_run_start(self, run_id: uuid.UUID) -> None:
        from app.workers.tasks import start_run_task

        start_run_task.apply_async(args=[str(run_id)])
        logger.info("run start dispatched to celery", extra={"run_id": str(run_id)})

    def drain(self) -> None:  # pragma: no cover - nothing local to drain
        return None


def build_executor(engine: object | None = None) -> WorkflowExecutor:
    from app.core.config import get_settings

    if get_settings().workflow_executor == "inline":
        return InlineExecutor(engine)
    return CeleryExecutor()
