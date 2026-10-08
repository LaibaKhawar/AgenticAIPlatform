"""Workflow engine.

Owns run and task lifecycle: planning, dependency scheduling, bounded parallel
dispatch, retries, cancellation, approval waits, resumption, failure handling
and audit events. All state lives in PostgreSQL, so a worker restart loses
nothing and a run can be resumed or inspected at any point.

The engine is executor-agnostic (see :mod:`app.orchestration.executor`) and
never blocks a web request: ``POST /api/v1/runs`` persists a QUEUED run and
returns.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import (
    ApprovalRequiredError,
    ResourceNotFoundError,
    VeriflowError,
    WorkflowCancelledError,
    is_retryable,
)
from app.core.logging import get_logger, log_context
from app.core.retry import backoff_delay
from app.core.telemetry import current_trace_id, span
from app.db.session import session_scope
from app.models.enums import (
    ActorType,
    AgentType,
    AuditEventType,
    RunStatus,
    TaskStatus,
    WorkflowMode,
    WorkflowType,
)
from app.models.workflow import Run, RunTask
from app.orchestration.dag import (
    INVESTIGATION_TASK_PREFIX,
    DagNode,
    blocked_tasks,
    ready_tasks,
    validate_plan,
)
from app.orchestration.executor import InlineExecutor, WorkflowExecutor, build_executor
from app.repositories.investigations import ApprovalRepository
from app.repositories.runs import RunRepository

logger = get_logger(__name__)

# Stage → progress percentage shown in the UI. Monotonic by construction.
STAGE_PROGRESS: dict[str, int] = {
    "objective_received": 2,
    "planning": 8,
    "candidate_selection": 18,
    "risk_screening": 30,
    "account_investigations": 55,
    "claim_verification": 72,
    "report_generation": 85,
    "approval": 92,
    "completion": 100,
}

# Tasks that aggregate a fan-out and may proceed when some branches failed.
TOLERANT_TASKS: frozenset[str] = frozenset({"investigate_accounts"})


@dataclass
class DispatchResult:
    dispatched: list[uuid.UUID]
    run_status: RunStatus
    stage: str


class WorkflowEngine:
    """Orchestrates one workflow type: the churn investigation DAG."""

    def __init__(self, executor: WorkflowExecutor | None = None) -> None:
        self.executor = executor or build_executor(self)
        if isinstance(self.executor, InlineExecutor):
            self.executor.bind(self)

    # ------------------------------------------------------------------ #
    # Run creation
    # ------------------------------------------------------------------ #

    def create_run(
        self,
        session: Session,
        *,
        objective: str,
        parameters: dict[str, Any],
        created_by: str = "operator",
        workflow_type: WorkflowType = WorkflowType.CHURN_INVESTIGATION,
    ) -> Run:
        """Persist a QUEUED run. Does not execute anything.

        Objective scope and structured parameters are resolved here, at request
        time, rather than inside the worker. Both checks are deterministic (a
        domain-term check and regex parameter extraction — no model call), so
        doing them synchronously costs nothing and means the caller learns
        immediately that an objective is out of scope, and learns exactly which
        parameters were resolved, instead of discovering it from a failed run
        minutes later. The planner repeats the scope check as defence in depth.
        """
        from app.agents.planner import ensure_supported_objective, resolve_parameters

        objective = objective.strip()
        ensure_supported_objective(objective)
        resolved = resolve_parameters(objective, parameters)

        repository = RunRepository(session)
        mode = resolved.get("workflow_mode") or WorkflowMode.STANDARD.value
        run = repository.create_run(
            objective=objective,
            workflow_type=workflow_type,
            workflow_mode=mode,
            created_by=created_by,
            metadata={
                "parameters": resolved,
                "requested_parameters": parameters,
                "requested_at": datetime.now(tz=UTC).isoformat(),
            },
        )
        repository.record_event(
            run_id=run.id,
            event_type=AuditEventType.RUN_CREATED,
            actor_type=ActorType.HUMAN,
            actor_id=created_by,
            message="Objective received and queued for execution.",
            payload={"objective": objective[:2000], "parameters": resolved},
            trace_id=current_trace_id(),
        )
        logger.info(
            "run created",
            extra={"run_id": str(run.id), "parameters": resolved, "created_by": created_by},
        )
        return run

    def enqueue(self, run_id: uuid.UUID) -> None:
        """Hand the run to the execution backend."""
        self.executor.submit_run_start(run_id)

    # ------------------------------------------------------------------ #
    # Planning
    # ------------------------------------------------------------------ #

    def start_run(self, run_id: uuid.UUID) -> None:
        """Plan the run, persist its tasks, and dispatch the first wave."""
        from app.agents import AgentRunContext, PlannerAgent

        with (
            log_context(run_id=str(run_id)),
            span("workflow", **{"run.id": str(run_id)}),
            session_scope() as session,
        ):
            repository = RunRepository(session)
            run = repository.get(run_id)
            if run is None:
                raise ResourceNotFoundError(f"run not found: {run_id}")
            if RunStatus(run.status).is_terminal:
                logger.info(
                    "ignoring start for a terminal run",
                    extra={"run_id": str(run_id), "status": run.status},
                )
                return
            if repository.list_tasks(run_id):
                # Duplicate delivery of start_run: planning already happened.
                logger.info("run already planned; advancing instead", extra={"run_id": str(run_id)})
                already_planned = True
            else:
                already_planned = False
                repository.set_status(run, RunStatus.RUNNING, stage="planning", progress=STAGE_PROGRESS["planning"])
                repository.record_event(
                    run_id=run_id,
                    event_type=AuditEventType.RUN_STARTED,
                    actor_type=ActorType.WORKER,
                    actor_id="workflow-engine",
                    message="Run started.",
                    trace_id=current_trace_id(),
                )

            if not already_planned:
                parameters = dict((run.run_metadata or {}).get("parameters") or {})
                planner = PlannerAgent()
                try:
                    output = planner.plan(
                        AgentRunContext(session=session, run_id=run_id, task_key="plan"),
                        objective=run.objective,
                        parameters=parameters,
                    )
                except VeriflowError as error:
                    self._fail_run(session, run, error, stage="planning")
                    return

                validate_plan(output.plan)
                self._persist_plan(session, run, output)

        if not self._is_terminal(run_id):
            self.advance(run_id)

    def _persist_plan(self, session: Session, run: Run, output: Any) -> None:
        repository = RunRepository(session)
        settings = get_settings()
        for task in output.plan.tasks:
            repository.create_task(
                run_id=run.id,
                task_key=task.id,
                agent_type=task.agent.value,
                description=task.description,
                stage=task.stage,
                dependencies=task.dependencies,
                input_payload={"parameters": {**output.parameters, **task.parameters}},
                max_retries=settings.task_max_retries,
            )
        repository.merge_metadata(
            run,
            {
                "parameters": output.parameters,
                "plan": output.plan.model_dump(mode="json"),
                "planned_at": datetime.now(tz=UTC).isoformat(),
            },
        )
        repository.record_event(
            run_id=run.id,
            event_type=AuditEventType.PLAN_CREATED,
            actor_type=ActorType.AGENT,
            actor_id=AgentType.PLANNER.value,
            message=f"Execution plan validated with {len(output.plan.tasks)} tasks.",
            payload={
                "task_count": len(output.plan.tasks),
                "task_ids": [task.id for task in output.plan.tasks],
                "parameters": output.parameters,
                "reasoning": output.plan.reasoning,
            },
            trace_id=current_trace_id(),
        )
        if output.call_record is not None:
            repository.record_llm_call(
                run_id=run.id,
                task_key="plan",
                agent=AgentType.PLANNER.value,
                provider=output.call_record.provider,
                model=output.call_record.model,
                operation=output.call_record.operation,
                prompt_tokens=output.call_record.prompt_tokens,
                completion_tokens=output.call_record.completion_tokens,
                latency_ms=output.call_record.latency_ms,
                estimated_cost_usd=output.call_record.estimated_cost_usd,
                attempts=output.call_record.attempts,
                valid_output=output.call_record.valid_output,
            )

    # ------------------------------------------------------------------ #
    # Scheduling
    # ------------------------------------------------------------------ #

    def advance(self, run_id: uuid.UUID) -> DispatchResult:
        """Dispatch every task that became ready, honouring concurrency limits."""
        settings = get_settings()
        to_dispatch: list[uuid.UUID] = []

        with session_scope() as session:
            repository = RunRepository(session)
            run = repository.get(run_id, for_update=True)
            if run is None:
                raise ResourceNotFoundError(f"run not found: {run_id}")
            status = RunStatus(run.status)
            if status.is_terminal:
                return DispatchResult([], status, run.current_stage)

            repository.reclaim_stale_tasks(timeout_seconds=settings.stale_task_timeout_seconds)
            tasks = repository.list_tasks(run_id)
            if not tasks:
                return DispatchResult([], status, run.current_stage)

            by_key = {task.task_key: task for task in tasks}
            statuses = {task.task_key: TaskStatus(task.status) for task in tasks}
            nodes = [DagNode(key=task.task_key, dependencies=tuple(task.dependencies)) for task in tasks]

            # Tasks waiting on an unresolved approval keep the run parked.
            waiting = [task for task in tasks if task.status == TaskStatus.WAITING_FOR_APPROVAL.value]
            if waiting:
                repository.set_status(
                    run,
                    RunStatus.WAITING_FOR_APPROVAL,
                    stage="approval",
                    progress=STAGE_PROGRESS["approval"],
                )
                return DispatchResult([], RunStatus.WAITING_FOR_APPROVAL, "approval")

            skipped = blocked_tasks(nodes, statuses, tolerant_keys=TOLERANT_TASKS)
            for key in skipped:
                task = by_key[key]
                repository.set_task_status(task, TaskStatus.SKIPPED)
                statuses[key] = TaskStatus.SKIPPED
                repository.record_event(
                    run_id=run_id,
                    task_id=task.id,
                    event_type=AuditEventType.TASK_SKIPPED,
                    actor_type=ActorType.WORKER,
                    actor_id="workflow-engine",
                    message=f"Task '{key}' cannot run because an upstream task failed.",
                )

            running = sum(1 for task in tasks if task.status in {TaskStatus.RUNNING.value, TaskStatus.QUEUED.value})
            candidates = ready_tasks(nodes, statuses, tolerant_keys=TOLERANT_TASKS)
            # Bound concurrency: investigations fan out, everything else is serial.
            budget = max(0, settings.max_parallel_investigations - running)

            for key in candidates:
                if budget <= 0:
                    break
                task = by_key[key]
                token = uuid.uuid4().hex
                if repository.mark_task_queued(task.id, token):
                    to_dispatch.append(task.id)
                    repository.record_event(
                        run_id=run_id,
                        task_id=task.id,
                        event_type=AuditEventType.TASK_QUEUED,
                        actor_type=ActorType.WORKER,
                        actor_id="workflow-engine",
                        message=f"Task '{key}' queued.",
                        payload={"agent": task.agent_type, "dependencies": task.dependencies},
                    )
                    budget -= 1

            statuses_after = {task.task_key: TaskStatus(task.status) for task in repository.list_tasks(run_id)}
            terminal = self._settle_run(session, run, statuses_after)
            stage = run.current_stage
            final_status = RunStatus(run.status)

        for task_id in to_dispatch:
            self.executor.submit_task(run_id, task_id)

        if not to_dispatch and not terminal:
            # Nothing dispatched and nothing finished: either work is in flight
            # on another worker, or the run is parked for approval.
            logger.debug("advance made no progress", extra={"run_id": str(run_id), "stage": stage})

        return DispatchResult(to_dispatch, final_status, stage)

    def _settle_run(self, session: Session, run: Run, statuses: dict[str, TaskStatus]) -> bool:
        """Complete or fail the run when no further progress is possible."""
        repository = RunRepository(session)
        if not statuses:
            return False
        if any(status is TaskStatus.WAITING_FOR_APPROVAL for status in statuses.values()):
            repository.set_status(
                run, RunStatus.WAITING_FOR_APPROVAL, stage="approval", progress=STAGE_PROGRESS["approval"]
            )
            return False

        active = [
            status
            for status in statuses.values()
            if status in {TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.RETRYING}
        ]
        if active:
            completed = sum(1 for status in statuses.values() if status is TaskStatus.COMPLETED)
            progress = max(
                STAGE_PROGRESS.get(run.current_stage, 0),
                int(completed / max(1, len(statuses)) * 95),
            )
            repository.set_status(run, RunStatus.RUNNING, progress=min(progress, 95))
            return False

        failures = [key for key, status in statuses.items() if status is TaskStatus.FAILED]
        # A per-customer investigation failing is tolerated — the aggregator
        # decides whether enough survived. Everything else, including the
        # aggregator itself, is a run-level failure.
        critical = [key for key in failures if not key.startswith(INVESTIGATION_TASK_PREFIX)]
        if critical:
            failed_tasks = [repository.get_task_by_key(run.id, key) for key in critical]
            message = "; ".join(f"{task.task_key}: {task.error_message or 'failed'}" for task in failed_tasks if task)
            repository.set_status(run, RunStatus.FAILED, stage=run.current_stage, error_message=message[:4000])
            repository.record_event(
                run_id=run.id,
                event_type=AuditEventType.RUN_FAILED,
                actor_type=ActorType.WORKER,
                actor_id="workflow-engine",
                message="Run failed.",
                payload={"failed_tasks": critical},
            )
            logger.error("run failed", extra={"run_id": str(run.id), "failed_tasks": critical})
            return True

        repository.set_status(run, RunStatus.COMPLETED, stage="completion", progress=100)
        repository.record_event(
            run_id=run.id,
            event_type=AuditEventType.RUN_COMPLETED,
            actor_type=ActorType.WORKER,
            actor_id="workflow-engine",
            message="Run completed.",
            payload={
                "tolerated_failures": [key for key in failures if key not in critical],
                "tasks": len(statuses),
            },
        )
        logger.info("run completed", extra={"run_id": str(run.id), "tasks": len(statuses)})
        return True

    # ------------------------------------------------------------------ #
    # Task execution
    # ------------------------------------------------------------------ #

    def execute_task(self, run_id: uuid.UUID, task_id: uuid.UUID) -> None:
        """Execute one task, then advance the run.

        Claiming, executing and recording the outcome each run in their own
        transaction. That separation is not cosmetic:

        * the claim commits before the long-running work starts, so the UI sees
          RUNNING immediately rather than at the end;
        * when a stage handler raises, its transaction is already rolled back
          and its session is unusable — recording the failure on that session
          would itself raise ``PendingRollbackError`` and leave the task stuck
          in QUEUED forever. The outcome is therefore always written through a
          fresh session.

        Idempotent against duplicate delivery: the claim is a conditional
        UPDATE, so a second delivery finds nothing to claim and returns.
        """
        from app.orchestration.stages import run_stage

        with log_context(run_id=str(run_id), task_id=str(task_id)):
            claimed = self._claim_task(run_id, task_id)
            if claimed is None:
                return
            task_key, agent_type, _stage = claimed

            advance = True
            with log_context(task=task_key, agent=agent_type):
                try:
                    with session_scope() as session:
                        repository = RunRepository(session)
                        run = repository.get(run_id)
                        task = repository.get_task(task_id)
                        if run is None or task is None:  # pragma: no cover - defensive
                            return
                        try:
                            with span(
                                f"task.{task_key.split(':')[0]}",
                                **{"task.key": task_key, "task.agent": agent_type},
                            ):
                                output = run_stage(self, session, run, task)
                        except ApprovalRequiredError as signal:
                            # A control-flow signal, not a failure. The session
                            # is healthy, and the approval records the handler
                            # just wrote must commit together with the parked
                            # state — rolling them back would leave a run
                            # waiting on approvals that do not exist.
                            self._park_for_approval(session, run, task, signal)
                            advance = False
                        except WorkflowCancelledError:
                            repository.set_task_status(task, TaskStatus.CANCELLED)
                            logger.info("task cancelled mid-flight", extra={"task": task_key})
                            advance = False
                        else:
                            repository.complete_task(task, output)
                            repository.record_event(
                                run_id=run_id,
                                task_id=task_id,
                                event_type=AuditEventType.TASK_COMPLETED,
                                actor_type=ActorType.AGENT,
                                actor_id=agent_type,
                                message=f"Task '{task_key}' completed.",
                                payload=_event_payload(output),
                                trace_id=current_trace_id(),
                            )
                except BaseException as error:
                    # Anything reaching here left the transaction rolled back,
                    # so the outcome is recorded through a fresh session.
                    advance = self._record_task_failure(run_id, task_id, task_key, agent_type, error)

        if advance and not self._is_terminal(run_id):
            self.advance(run_id)

    def _claim_task(self, run_id: uuid.UUID, task_id: uuid.UUID) -> tuple[str, str, str] | None:
        """Atomically take ownership of a task. Returns ``(key, agent, stage)``."""
        with session_scope() as session:
            repository = RunRepository(session)
            run = repository.get(run_id)
            if run is None:
                logger.warning("task for unknown run", extra={"run_id": str(run_id)})
                return None
            if RunStatus(run.status) in {RunStatus.CANCELLED, RunStatus.FAILED}:
                # Late delivery after the run ended: stop, never resurrect it.
                task = repository.get_task(task_id)
                if task is not None and not TaskStatus(task.status).is_terminal:
                    repository.set_task_status(task, TaskStatus.CANCELLED)
                logger.info(
                    "dropping task for terminal run",
                    extra={"run_id": str(run_id), "status": run.status},
                )
                return None

            task = repository.claim_task(task_id)
            if task is None:
                logger.info(
                    "task already claimed; treating delivery as duplicate",
                    extra={"task_id": str(task_id)},
                )
                return None

            repository.set_status(
                run, RunStatus.RUNNING, stage=task.stage, progress=STAGE_PROGRESS.get(task.stage)
            )
            repository.record_event(
                run_id=run_id,
                task_id=task.id,
                event_type=AuditEventType.TASK_STARTED,
                actor_type=ActorType.AGENT,
                actor_id=task.agent_type,
                message=f"Task '{task.task_key}' started.",
                trace_id=current_trace_id(),
            )
            return task.task_key, task.agent_type, task.stage

    def _record_task_failure(
        self,
        run_id: uuid.UUID,
        task_id: uuid.UUID,
        task_key: str,
        agent_type: str,
        error: BaseException,
    ) -> bool:
        """Retry transient failures with backoff; fail permanent ones.

        Runs in its own session: the handler's transaction has already been
        rolled back by the time we get here, so reusing that session would
        raise and strand the task.

        Returns whether the engine should advance the run afterwards.
        """
        retryable = is_retryable(error)
        message = f"{type(error).__name__}: {error}"
        retry_delay: float | None = None

        with session_scope() as session:
            repository = RunRepository(session)
            run = repository.get(run_id)
            task = repository.get_task(task_id)
            if run is None or task is None:  # pragma: no cover - defensive
                return False

            if retryable and task.retry_count < task.max_retries:
                repository.schedule_retry(task, message)
                retry_delay = backoff_delay(task.retry_count)
                repository.set_status(run, RunStatus.RETRYING, stage=task.stage)
                repository.record_event(
                    run_id=run_id,
                    task_id=task_id,
                    event_type=AuditEventType.TASK_RETRYING,
                    actor_type=ActorType.WORKER,
                    actor_id="workflow-engine",
                    message=(
                        f"Task '{task_key}' hit a transient failure and will retry "
                        f"(attempt {task.retry_count} of {task.max_retries})."
                    ),
                    payload={
                        "error_type": type(error).__name__,
                        "retry_count": task.retry_count,
                        "delay_seconds": round(retry_delay, 2),
                    },
                )
                logger.warning(
                    "task scheduled for retry",
                    extra={
                        "task": task_key,
                        "retry_count": task.retry_count,
                        "max_retries": task.max_retries,
                        "error_type": type(error).__name__,
                    },
                )
            else:
                repository.fail_task(task, message)
                repository.record_event(
                    run_id=run_id,
                    task_id=task_id,
                    event_type=AuditEventType.TASK_FAILED,
                    actor_type=ActorType.WORKER,
                    actor_id=agent_type,
                    message=f"Task '{task_key}' failed: {message[:500]}",
                    payload={
                        "error_type": type(error).__name__,
                        "retryable": retryable,
                        "retry_count": task.retry_count,
                        "details": getattr(error, "details", {}),
                    },
                )
                logger.error(
                    "task failed",
                    extra={
                        "task": task_key,
                        "error_type": type(error).__name__,
                        "retryable": retryable,
                        "retry_count": task.retry_count,
                    },
                )

        if retry_delay is not None:
            # Dispatched after the transaction committed, so the worker that
            # picks it up always sees the RETRYING state.
            self.executor.submit_task(run_id, task_id, delay_seconds=retry_delay)
            return False
        return True

    def _park_for_approval(
        self, session: Session, run: Run, task: RunTask, signal: ApprovalRequiredError
    ) -> None:
        """Record the parked state on the stage handler's own session."""
        repository = RunRepository(session)
        task.status = TaskStatus.WAITING_FOR_APPROVAL.value
        task.output_payload = signal.details
        session.flush()
        repository.set_status(
            run, RunStatus.WAITING_FOR_APPROVAL, stage="approval", progress=STAGE_PROGRESS["approval"]
        )
        repository.record_event(
            run_id=run.id,
            task_id=task.id,
            event_type=AuditEventType.APPROVAL_REQUESTED,
            actor_type=ActorType.SYSTEM,
            actor_id="approval-policy",
            message=signal.message,
            payload=signal.details,
        )
        logger.info(
            "run parked for human approval",
            extra={"run_id": str(run.id), "task": task.task_key, "details": signal.details},
        )

    def _fail_run(self, session: Session, run: Run, error: VeriflowError, *, stage: str) -> None:
        repository = RunRepository(session)
        repository.set_status(run, RunStatus.FAILED, stage=stage, error_message=f"{error.code}: {error.message}")
        repository.record_event(
            run_id=run.id,
            event_type=(AuditEventType.PLAN_REJECTED if stage == "planning" else AuditEventType.RUN_FAILED),
            actor_type=ActorType.SYSTEM,
            actor_id="workflow-engine",
            message=error.message,
            payload={"code": error.code, "details": error.details},
        )
        logger.error("run failed", extra={"run_id": str(run.id), "stage": stage, "code": error.code})

    # ------------------------------------------------------------------ #
    # Control operations
    # ------------------------------------------------------------------ #

    def cancel_run(self, run_id: uuid.UUID) -> Run:
        with session_scope() as session:
            repository = RunRepository(session)
            run = repository.request_cancellation(run_id)
            if run is None:
                raise ResourceNotFoundError(f"run not found: {run_id}")
            repository.record_event(
                run_id=run_id,
                event_type=AuditEventType.RUN_CANCELLED,
                actor_type=ActorType.HUMAN,
                actor_id="operator",
                message="Run cancelled by operator; no further work will be scheduled.",
            )
            logger.info("run cancelled", extra={"run_id": str(run_id)})
            return run

    def resume_after_approval(self, run_id: uuid.UUID) -> None:
        """Continue a parked run once every approval request is resolved."""
        resume = False
        with session_scope() as session:
            repository = RunRepository(session)
            approvals = ApprovalRepository(session)
            run = repository.get(run_id, for_update=True)
            if run is None:
                raise ResourceNotFoundError(f"run not found: {run_id}")
            if RunStatus(run.status).is_terminal:
                logger.info(
                    "approval resolved for a terminal run; nothing to resume",
                    extra={"run_id": str(run_id), "status": run.status},
                )
                return
            if not approvals.all_resolved(run_id):
                logger.info(
                    "approvals still pending; run stays parked",
                    extra={
                        "run_id": str(run_id),
                        "pending": approvals.count_approvals(run_id=run_id, status=None),
                    },
                )
                return

            parked = [
                task for task in repository.list_tasks(run_id) if task.status == TaskStatus.WAITING_FOR_APPROVAL.value
            ]
            for task in parked:
                decisions = [
                    {
                        "approval_id": str(approval.id),
                        "action_type": approval.action_type,
                        "status": approval.status,
                        "reviewed_by": approval.reviewed_by,
                        "reviewer_comment": approval.reviewer_comment,
                    }
                    for approval in approvals.list_approvals(run_id=run_id, limit=200)
                ]
                repository.complete_task(task, {**(task.output_payload or {}), "approval_decisions": decisions})
                repository.record_event(
                    run_id=run_id,
                    task_id=task.id,
                    event_type=AuditEventType.TASK_COMPLETED,
                    actor_type=ActorType.SYSTEM,
                    actor_id="approval-policy",
                    message="All approval requests resolved; workflow resumed.",
                    payload={"decisions": decisions},
                )
            repository.set_status(run, RunStatus.RUNNING, stage="completion")
            resume = True

        if resume:
            self.advance(run_id)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _is_terminal(self, run_id: uuid.UUID) -> bool:
        with session_scope() as session:
            run = RunRepository(session).get(run_id)
            return run is None or RunStatus(run.status).is_terminal

    def ensure_not_cancelled(self, session: Session, run_id: uuid.UUID) -> None:
        if RunRepository(session).is_cancelled(run_id):
            raise WorkflowCancelledError(f"run {run_id} was cancelled")


def _event_payload(output: dict[str, Any] | None) -> dict[str, Any]:
    """Keep audit payloads small: summaries, not whole result sets."""
    if not output:
        return {}
    summary: dict[str, Any] = {}
    for key, value in output.items():
        if isinstance(value, (int, float, bool, str)) or value is None:
            summary[key] = value if not isinstance(value, str) else value[:500]
        elif isinstance(value, list):
            summary[f"{key}_count"] = len(value)
        elif isinstance(value, dict):
            summary[key] = {
                inner_key: inner for inner_key, inner in value.items() if isinstance(inner, (int, float, bool))
            }
    return summary


_engine: WorkflowEngine | None = None


def get_engine() -> WorkflowEngine:
    global _engine
    if _engine is None:
        _engine = WorkflowEngine()
    return _engine


def set_engine(engine: WorkflowEngine | None) -> None:
    """Install a specific engine (tests use an inline executor)."""
    global _engine
    _engine = engine
