# Workflow

## Run states

| State | Meaning |
|---|---|
| `PENDING` | Reserved; runs are created `QUEUED`. |
| `QUEUED` | Persisted and dispatched. No work started. |
| `RUNNING` | At least one task executing or dispatchable. |
| `RETRYING` | A task hit a transient failure and is scheduled for retry. |
| `WAITING_FOR_APPROVAL` | Parked on a human decision. No further work scheduled. |
| `COMPLETED` | Every task terminal, no critical failure. |
| `FAILED` | A non-tolerated task exhausted its options. |
| `CANCELLED` | Operator cancelled. |

Terminal: `COMPLETED`, `FAILED`, `CANCELLED`. A terminal run never schedules
work again, and a late task delivery for one is dropped rather than executed.

## Task states

`PENDING → QUEUED → RUNNING → COMPLETED` on the happy path, with:

- `RETRYING` — transient failure, budget remaining; `retry_count` incremented,
  `started_at` cleared, re-dispatched with backoff.
- `WAITING_FOR_APPROVAL` — the approval task, parked.
- `FAILED` — permanent failure, or transient with the budget exhausted.
- `SKIPPED` — can never run because an ancestor died.
- `CANCELLED` — the run was cancelled.

## The canonical plan

| Task | Agent | Stage | Depends on |
|---|---|---|---|
| `select_candidates` | data | candidate_selection | — |
| `screen_risk` | risk | risk_screening | `select_candidates` |
| `investigate:<id>` | investigator | account_investigations | `screen_risk` *(created at runtime)* |
| `investigate_accounts` | investigator | account_investigations | `screen_risk` + every `investigate:*` |
| `verify_claims` | verifier | claim_verification | `investigate_accounts` |
| `generate_report` | reporter | report_generation | `verify_claims` |
| `request_approvals` | policy | approval | `generate_report` |
| `finalize` | system | completion | `request_approvals` |

`REQUIRED_TASK_KEYS` are `select_candidates`, `screen_risk`, `verify_claims`,
`generate_report`, `finalize` — a plan omitting any is rejected.

## Plan validation

`validate_plan()` rejects, reporting **every** problem at once so a failed run
tells an operator exactly what the model got wrong:

- more tasks than `MAX_PLAN_TASKS`
- duplicate task ids
- agents the platform does not have (including `planner` — it cannot schedule
  itself)
- task ids with no executor behind them
- dependencies on undefined tasks
- self-dependency
- missing required tasks
- dependency cycles (DFS with colouring; the cycle path is reported)

`PlanValidationError` is permanent — never retried with the same input.

## Scheduling

```
advance(run_id):                         # under a row lock on the run
    reclaim_stale_tasks(timeout)         # dead workers → RETRYING or FAILED
    if any WAITING_FOR_APPROVAL: park and return
    for key in blocked_tasks(...):  mark SKIPPED + audit event
    budget = MAX_PARALLEL_INVESTIGATIONS - (RUNNING + QUEUED)
    for key in ready_tasks(...)[:budget]:
        mark_task_queued(...)            # conditional UPDATE
        record TASK_QUEUED
    settle_run(...)
    dispatch the claimed tasks           # after the transaction commits
```

Dispatch happens after commit so a worker always sees `QUEUED`.

## Run settlement

```
any WAITING_FOR_APPROVAL              → WAITING_FOR_APPROVAL
any PENDING/QUEUED/RUNNING/RETRYING   → RUNNING, progress from completion ratio
any FAILED task not named investigate:* → FAILED, error lists the failing tasks
otherwise                             → COMPLETED, progress 100
```

A failed `investigate:<id>` is tolerated. A failed `investigate_accounts`
aggregator is not — if every branch died there is nothing to verify or report,
and the run should say so.

## Retries

```python
delay = uniform(0, min(cap, base * 2 ** (attempt - 1)))   # full jitter
```

Full jitter rather than fixed backoff because the common cause is a provider
rate limit hitting several workers at once; identical delays would retry in
lockstep.

Classification is by exception type, never string matching. `is_retryable()`
treats unknown exceptions as **permanent**, so a bug surfaces as a clear failed
run instead of being retried three times and hidden.

## Approval

```
request_approvals:
    for each investigation, for each recommended action:
        decision = decide(action_type, workflow_mode)     # deterministic
        if not required: record as auto-approved, continue
        approvals.request(..., idempotency_key=...)       # idempotent
    if any pending: raise ApprovalRequiredError(details)
```

The error is caught inside the stage's own transaction, so the approval rows
commit together with the parked state.

Resuming:

```
POST /api/v1/approvals/{id}/approve|reject
    → 404 if unknown
    → 409 if already resolved          (never silently overwrite a review)
    → 409 if the parent run is terminal
    → resolve, record APPROVAL_GRANTED/REJECTED
    → commit
    → engine.resume_after_approval(run_id)
```

`resume_after_approval` is a no-op while any request for the run is still
pending, so resolving them in any order works and only the last one resumes the
run. It completes the parked task with the decision set attached, then advances.

Because all of this lives in PostgreSQL, a brand-new engine in a brand-new
process resumes a parked run correctly — covered by an e2e test that discards
the engine and builds a fresh one.

## Cancellation

```
POST /api/v1/runs/{id}/cancel
    → 409 if already terminal
    → run CANCELLED; PENDING/QUEUED/RETRYING/WAITING_FOR_APPROVAL tasks CANCELLED
    → record RUN_CANCELLED
```

A task already executing finishes its current step; `ensure_not_cancelled()` is
checked at the top of every stage, so in-flight work unwinds with
`WorkflowCancelledError`. A delivery arriving after cancellation is dropped in
the claim transaction.

## Idempotency

| Operation | Guard |
|---|---|
| duplicate task delivery | conditional `UPDATE … WHERE status IN ('QUEUED','RETRYING')` |
| duplicate `start_run` | if tasks already exist, skip planning and just advance |
| evidence write | unique `(run_id, customer_id, source_id)` → upsert |
| claim write | unique `(run_id, claim_key)` → upsert |
| investigation write | unique `(run_id, customer_id)` → upsert |
| report write | unique `(run_id)` → upsert |
| approval request | unique `(run_id, idempotency_key)` → returns the existing row |

## Stage → progress

`objective_received` 2 · `planning` 8 · `candidate_selection` 18 ·
`risk_screening` 30 · `account_investigations` 55 · `claim_verification` 72 ·
`report_generation` 85 · `approval` 92 · `completion` 100.

Monotonic by construction; while tasks are in flight, progress is the greater of
the stage marker and the completion ratio.
