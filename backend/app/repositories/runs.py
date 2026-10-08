"""Run, task and audit persistence.

Task state transitions use conditional UPDATE … WHERE status = … statements so
two workers (or a duplicate Celery delivery) cannot both claim the same task.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.enums import ActorType, AuditEventType, RunStatus, TaskStatus, WorkflowType
from app.models.workflow import AuditEvent, LlmCall, Run, RunTask

logger = get_logger(__name__)


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


class RunRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # --- runs -------------------------------------------------------------

    def create_run(
        self,
        *,
        objective: str,
        workflow_type: WorkflowType,
        workflow_mode: str,
        created_by: str,
        metadata: dict[str, Any],
    ) -> Run:
        run = Run(
            objective=objective,
            workflow_type=workflow_type.value,
            workflow_mode=workflow_mode,
            status=RunStatus.QUEUED.value,
            progress=0,
            current_stage="objective_received",
            created_at=utcnow(),
            created_by=created_by,
            run_metadata=metadata,
        )
        self.session.add(run)
        self.session.flush()
        return run

    def get(self, run_id: uuid.UUID, *, for_update: bool = False) -> Run | None:
        query = select(Run).where(Run.id == run_id)
        if for_update:
            query = query.with_for_update()
        return self.session.scalars(query).first()

    def list_runs(self, *, status: RunStatus | None = None, limit: int = 25, offset: int = 0) -> list[Run]:
        query = select(Run).order_by(Run.created_at.desc()).limit(limit).offset(offset)
        if status:
            query = query.where(Run.status == status.value)
        return list(self.session.scalars(query))

    def count_runs(self, *, status: RunStatus | None = None) -> int:
        query = select(func.count()).select_from(Run)
        if status:
            query = query.where(Run.status == status.value)
        return int(self.session.scalar(query) or 0)

    def set_status(
        self,
        run: Run,
        status: RunStatus,
        *,
        stage: str | None = None,
        progress: int | None = None,
        error_message: str | None = None,
    ) -> Run:
        run.status = status.value
        if stage is not None:
            run.current_stage = stage
        if progress is not None:
            run.progress = max(0, min(100, progress))
        if status is RunStatus.RUNNING and run.started_at is None:
            run.started_at = utcnow()
        if status is RunStatus.COMPLETED:
            run.completed_at = utcnow()
            run.progress = 100
        if status is RunStatus.FAILED:
            run.failed_at = utcnow()
            run.error_message = error_message
        if status is RunStatus.CANCELLED:
            run.completed_at = utcnow()
        if error_message and status is not RunStatus.FAILED:
            run.error_message = error_message
        self.session.flush()
        return run

    def merge_metadata(self, run: Run, extra: dict[str, Any]) -> Run:
        merged = dict(run.run_metadata or {})
        merged.update(extra)
        run.run_metadata = merged
        self.session.flush()
        return run

    def request_cancellation(self, run_id: uuid.UUID) -> Run | None:
        """Mark a run cancelled. Workers observe this before each task."""
        run = self.get(run_id, for_update=True)
        if run is None:
            return None
        if RunStatus(run.status).is_terminal:
            return run
        self.set_status(run, RunStatus.CANCELLED, stage="cancelled")
        self.session.execute(
            update(RunTask)
            .where(
                RunTask.run_id == run_id,
                RunTask.status.in_(
                    [
                        TaskStatus.PENDING.value,
                        TaskStatus.QUEUED.value,
                        TaskStatus.RETRYING.value,
                        TaskStatus.WAITING_FOR_APPROVAL.value,
                    ]
                ),
            )
            .values(status=TaskStatus.CANCELLED.value, completed_at=utcnow())
        )
        self.session.flush()
        return run

    def is_cancelled(self, run_id: uuid.UUID) -> bool:
        status = self.session.scalar(select(Run.status).where(Run.id == run_id))
        return status in {RunStatus.CANCELLED.value, RunStatus.FAILED.value}

    # --- tasks ------------------------------------------------------------

    def create_task(
        self,
        *,
        run_id: uuid.UUID,
        task_key: str,
        agent_type: str,
        description: str,
        stage: str,
        dependencies: Sequence[str],
        input_payload: dict[str, Any] | None = None,
        max_retries: int = 3,
    ) -> RunTask:
        task = RunTask(
            run_id=run_id,
            task_key=task_key,
            agent_type=agent_type,
            description=description,
            stage=stage,
            status=TaskStatus.PENDING.value,
            dependencies=list(dependencies),
            input_payload=input_payload or {},
            max_retries=max_retries,
            created_at=utcnow(),
        )
        self.session.add(task)
        self.session.flush()
        return task

    def get_task(self, task_id: uuid.UUID) -> RunTask | None:
        return self.session.get(RunTask, task_id)

    def get_task_by_key(self, run_id: uuid.UUID, task_key: str) -> RunTask | None:
        return self.session.scalars(
            select(RunTask).where(RunTask.run_id == run_id, RunTask.task_key == task_key)
        ).first()

    def list_tasks(self, run_id: uuid.UUID) -> list[RunTask]:
        return list(
            self.session.scalars(
                select(RunTask).where(RunTask.run_id == run_id).order_by(RunTask.created_at, RunTask.task_key)
            )
        )

    def count_tasks_by_status(self, run_id: uuid.UUID) -> dict[str, int]:
        rows = self.session.execute(
            select(RunTask.status, func.count()).where(RunTask.run_id == run_id).group_by(RunTask.status)
        ).all()
        return {str(status): int(count) for status, count in rows}

    def mark_task_queued(self, task_id: uuid.UUID, dispatch_token: str) -> bool:
        """Atomically move PENDING/RETRYING → QUEUED. False if already claimed."""
        result = cast(
            CursorResult[Any],
            self.session.execute(
                update(RunTask)
                .where(
                    RunTask.id == task_id,
                    RunTask.status.in_([TaskStatus.PENDING.value, TaskStatus.RETRYING.value]),
                )
                .values(status=TaskStatus.QUEUED.value, dispatch_token=dispatch_token)
            ),
        )
        self.session.flush()
        return bool(result.rowcount)

    def claim_task(self, task_id: uuid.UUID) -> RunTask | None:
        """Atomically move QUEUED/RETRYING → RUNNING.

        Returns ``None`` when another worker already claimed it, which is how a
        duplicate Celery delivery becomes a no-op instead of double work.
        """
        result = cast(
            CursorResult[Any],
            self.session.execute(
                update(RunTask)
                .where(
                    RunTask.id == task_id,
                    RunTask.status.in_([TaskStatus.QUEUED.value, TaskStatus.RETRYING.value]),
                )
                .values(status=TaskStatus.RUNNING.value, started_at=utcnow())
            ),
        )
        self.session.flush()
        if not result.rowcount:
            return None
        task = self.session.get(RunTask, task_id)
        if task is not None:
            self.session.refresh(task)
        return task

    def complete_task(self, task: RunTask, output: dict[str, Any] | None = None) -> RunTask:
        task.status = TaskStatus.COMPLETED.value
        task.output_payload = output or {}
        task.completed_at = utcnow()
        task.error_message = None
        if task.started_at:
            task.duration_ms = int((task.completed_at - task.started_at).total_seconds() * 1000)
        self.session.flush()
        return task

    def fail_task(self, task: RunTask, error: str) -> RunTask:
        task.status = TaskStatus.FAILED.value
        task.error_message = error[:4000]
        task.completed_at = utcnow()
        if task.started_at:
            task.duration_ms = int((task.completed_at - task.started_at).total_seconds() * 1000)
        self.session.flush()
        return task

    def schedule_retry(self, task: RunTask, error: str) -> RunTask:
        task.status = TaskStatus.RETRYING.value
        task.retry_count += 1
        task.error_message = error[:4000]
        task.started_at = None
        self.session.flush()
        return task

    def set_task_status(self, task: RunTask, status: TaskStatus) -> RunTask:
        task.status = status.value
        if status.is_terminal:
            task.completed_at = utcnow()
        self.session.flush()
        return task

    def extend_task_dependencies(self, task: RunTask, extra: Sequence[str]) -> RunTask:
        merged = list(dict.fromkeys([*task.dependencies, *extra]))
        task.dependencies = merged
        self.session.flush()
        return task

    def reclaim_stale_tasks(self, *, timeout_seconds: int) -> int:
        """Return RUNNING tasks whose worker vanished to RETRYING.

        Called by the orchestrator before scheduling so a killed worker cannot
        strand a run forever.
        """
        cutoff = utcnow().timestamp() - timeout_seconds
        stale = list(
            self.session.scalars(
                select(RunTask).where(RunTask.status == TaskStatus.RUNNING.value, RunTask.started_at.isnot(None))
            )
        )
        reclaimed = 0
        for task in stale:
            if task.started_at and task.started_at.timestamp() < cutoff:
                if task.retry_count < task.max_retries:
                    self.schedule_retry(task, "worker did not report back within the task timeout")
                else:
                    self.fail_task(task, "worker did not report back and the retry budget is exhausted")
                reclaimed += 1
        self.session.flush()
        return reclaimed

    # --- audit / telemetry ------------------------------------------------

    def record_event(
        self,
        *,
        run_id: uuid.UUID | None,
        event_type: AuditEventType,
        actor_type: ActorType,
        actor_id: str,
        message: str = "",
        payload: dict[str, Any] | None = None,
        task_id: uuid.UUID | None = None,
        customer_id: uuid.UUID | None = None,
        trace_id: str | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            run_id=run_id,
            task_id=task_id,
            customer_id=customer_id,
            event_type=event_type.value,
            actor_type=actor_type.value,
            actor_id=actor_id,
            message=message[:4000],
            payload=payload or {},
            trace_id=trace_id,
            created_at=utcnow(),
        )
        self.session.add(event)
        self.session.flush()
        return event

    def list_events(self, run_id: uuid.UUID, *, limit: int = 500) -> list[AuditEvent]:
        return list(
            self.session.scalars(
                select(AuditEvent).where(AuditEvent.run_id == run_id).order_by(AuditEvent.created_at.asc()).limit(limit)
            )
        )

    def record_llm_call(
        self,
        *,
        run_id: uuid.UUID | None,
        task_key: str | None,
        agent: str,
        provider: str,
        model: str,
        operation: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: int,
        estimated_cost_usd: float,
        attempts: int,
        valid_output: bool,
    ) -> None:
        self.session.add(
            LlmCall(
                run_id=run_id,
                task_key=task_key,
                agent=agent,
                provider=provider,
                model=model,
                operation=operation,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
                estimated_cost_usd=estimated_cost_usd,
                attempts=attempts,
                valid_output=valid_output,
                created_at=utcnow(),
            )
        )
        self.session.flush()

    def llm_usage_for_run(self, run_id: uuid.UUID) -> dict[str, Any]:
        row = self.session.execute(
            select(
                func.count(),
                func.coalesce(func.sum(LlmCall.prompt_tokens), 0),
                func.coalesce(func.sum(LlmCall.completion_tokens), 0),
                func.coalesce(func.sum(LlmCall.estimated_cost_usd), 0),
                func.coalesce(func.avg(LlmCall.latency_ms), 0),
            ).where(LlmCall.run_id == run_id)
        ).one()
        return {
            "calls": int(row[0]),
            "prompt_tokens": int(row[1]),
            "completion_tokens": int(row[2]),
            "total_tokens": int(row[1]) + int(row[2]),
            "estimated_cost_usd": round(float(row[3]), 6),
            "avg_latency_ms": round(float(row[4]), 1),
        }
