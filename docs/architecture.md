# Architecture

## The shape of the system

Four runtime components, each with one job:

| Component | Responsibility | Stateless? |
|---|---|---|
| **Frontend** (Next.js) | Operator UI. Reads the API; holds no business logic. | yes |
| **API** (FastAPI) | Request validation, auth boundary, structured errors, read models. Creates runs; never executes them. | yes |
| **Worker** (Celery) | Executes tasks. Horizontally scalable. | yes |
| **PostgreSQL + pgvector** | All state: domain data, vectors, workflow state, evidence, audit. | the only stateful component |

Redis is the broker and result backend. It carries no durable state the system
depends on — if Redis is wiped, runs are recoverable from PostgreSQL, because
the task graph and every task's status live there.

## Why the workflow engine is a library, not a service

`app/orchestration/engine.py` contains all orchestration logic: dependency
scheduling, retry accounting, cancellation, approval parking, run settlement.
It depends on an `Executor` protocol:

```python
class WorkflowExecutor(Protocol):
    def submit_task(self, run_id, task_id, *, delay_seconds: float = 0.0) -> None: ...
    def submit_run_start(self, run_id) -> None: ...
    def drain(self) -> None: ...
```

Two implementations ship:

- **`CeleryExecutor`** — production. Pushes onto the `veriflow` queue.
- **`InlineExecutor`** — runs tasks in-process through an explicit work queue
  (not recursion: a fan-out of N investigations would otherwise nest N stack
  frames). Used by the whole test suite and by `WORKFLOW_EXECUTOR=inline`.

This has three consequences worth stating:

1. **Tests drive the real engine.** The e2e scenarios are not testing a
   simplified path — they execute the same scheduling, retry and settlement code
   the workers run.
2. **Celery is replaceable.** A Temporal migration is a third executor plus
   activity wrappers. No workflow logic moves.
3. **Celery knows almost nothing.** It understands two tasks — "plan this run"
   and "execute this task" — and nothing about stages, dependencies or
   approvals.

The cost is that the engine is not a distributed scheduler: a run advances when
a worker finishes a task and calls `advance()`, which takes a row lock on the
run to serialise concurrent finishers. At this scale that is simpler and more
debuggable than a separate scheduler process.

## Request path: creating a run

```
POST /api/v1/runs
  ├─ Pydantic validates the body (objective length, enum values, bounds)
  ├─ ensure_supported_objective()      ← deterministic domain check → 422 if out of scope
  ├─ resolve_parameters()              ← deterministic regex over the objective
  ├─ RunRepository.create_run()        ← persists status=QUEUED
  ├─ record RUN_CREATED audit event
  ├─ session.commit()                  ← committed BEFORE dispatch
  └─ executor.submit_run_start()       → returns 202 immediately
```

Two details that matter:

- **Scope and parameter resolution happen at request time**, not in the worker.
  Both are deterministic (a domain-term check and regex extraction — no model
  call), so doing them synchronously costs nothing and means the caller
  immediately learns an objective is out of scope, and learns exactly which
  parameters were resolved, instead of discovering it from a failed run minutes
  later.
- **The commit precedes the dispatch.** A worker can never pick up a run that is
  not yet visible to other connections.

## Execution path: one task

```
Celery delivers veriflow.execute_task(run_id, task_id)
  │
  ├─ TRANSACTION 1 — claim
  │    ├─ run terminal?  → cancel the task, stop   (late delivery after cancel)
  │    ├─ claim_task()   → conditional UPDATE; None means a duplicate delivery
  │    ├─ run → RUNNING, stage, progress
  │    └─ record TASK_STARTED                      ← commits, so the UI sees RUNNING now
  │
  ├─ TRANSACTION 2 — execute
  │    ├─ run_stage(engine, session, run, task)
  │    ├─ ApprovalRequiredError  → park, same session (approval rows must commit)
  │    ├─ WorkflowCancelledError → task CANCELLED
  │    └─ success                → complete_task + TASK_COMPLETED
  │
  ├─ TRANSACTION 3 (only on failure) — record the outcome in a FRESH session
  │    ├─ transient + budget left → RETRYING, re-dispatch with backoff
  │    └─ otherwise              → FAILED
  │
  └─ advance(run_id)
```

### Why three transactions

This was a bug, not a design flourish. A stage handler that fails mid-flush (a
unique violation, say) leaves its transaction rolled back and its session
unusable. Recording the failure on that session raises `PendingRollbackError` —
so the failure was never recorded, the task stayed `QUEUED` forever, and the run
hung instead of failing. The outcome is therefore always written through a fresh
session.

`ApprovalRequiredError` is the exception: it is a control-flow signal on a
*healthy* session, and the approval rows the handler just wrote must commit
together with the parked state. Rolling them back would leave a run waiting on
approvals that do not exist — which is exactly what happened when this was first
restructured.

## Scheduling

`advance()` runs inside a row lock on the run:

```
reclaim stale RUNNING tasks (dead workers)
if any task is WAITING_FOR_APPROVAL → park the run, return
skip tasks whose ancestors died
dispatch ready tasks, up to MAX_PARALLEL_INVESTIGATIONS in flight
settle the run: COMPLETED, FAILED, or still RUNNING
```

**Readiness** means every dependency is `COMPLETED`. **Tolerant** tasks — the
`investigate_accounts` aggregator — also accept `FAILED`/`SKIPPED` dependencies,
so one account's failure does not strand the run; but if *every* branch died the
aggregator is blocked and skipped, and the run fails.

## Fan-out

The planner emits a single `investigate_accounts` task. At runtime,
`screen_risk` creates one `investigate:<external_id>` task per selected account
and extends the aggregator's dependencies to include them.

Parallelism is therefore a property of the **persisted graph**, not of a worker's
in-memory loop. The consequences: it survives a restart, it is visible in the UI
and the API, and concurrency is bounded by how many tasks `advance()` will
dispatch rather than by thread count.

## Determinism boundary

The single most important architectural line in this codebase:

| Deterministic code owns | The model is used for |
|---|---|
| candidate selection (SQL) | planning (within validated bounds) |
| all arithmetic and date maths | qualitative interpretation |
| risk scoring and ranking | drafting cited claims |
| claim/evidence rule checks | judging claims against evidence |
| approval policy | report prose |
| retry classification | |

Cost control falls out of this: only the shortlist reaches an LLM, and three of
seven agents call no model at all.

## Configuration

`app/core/config.py` is the single source. Always reached through
`get_settings()` — never a module-level instance — so tests can override one
field on the cached object and every caller observes it.

Two computed properties encode important behaviour:

- `effective_llm_provider` falls back to the deterministic provider when
  `LLM_PROVIDER=openai` but no key is present, so the platform stays runnable
  instead of failing at the first agent call.
- `failure_injection_active` is always `False` when `APP_ENV=production`,
  whatever the rates say.

## The engine URL pin

`app/db/session.py` keeps the URL it was explicitly configured with, and
`get_engine()` prefers it over `settings.database_url`. This is not decoration:
the FastAPI lifespan disposes the engine on shutdown, and when the app is
embedded in a test client, that shutdown dropped a test-configured engine and
had the next call rebuild it against the development database — which the suite
then truncated. The pin survives a dispose; `reset_engine_configuration()` is
the explicit way back.
