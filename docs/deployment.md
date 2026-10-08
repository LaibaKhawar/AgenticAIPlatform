# Deployment

## Local

```bash
cp .env.example .env
make up        # build, start, migrate
make seed      # 3,000 customers (~17s)
```

`docker compose up --build` works directly; `make up` adds health-gating and
prints the URLs.

## Services

| Service | Image | Port | Health check |
|---|---|---|---|
| `postgres` | `pgvector/pgvector:pg16` | 5433→5432 | `pg_isready` |
| `redis` | `redis:7-alpine` | 6380→6379 | `redis-cli ping` |
| `migrate` | backend | — | runs `alembic upgrade head`, then exits |
| `backend` | backend | 8000 | `GET /health/live` |
| `worker` | backend | — | `celery inspect ping` |
| `frontend` | frontend | 3000 | `GET /api/ping` |

Host ports 5433/6380 avoid colliding with a local PostgreSQL or Redis.

### No startup race

`migrate` is a one-shot service. `backend` and `worker` both declare:

```yaml
depends_on:
  postgres: { condition: service_healthy }
  migrate:  { condition: service_completed_successfully }
```

So migrations complete exactly once before any application process starts.
Running migrations from the API or the worker would race when both start
together, or when the worker is scaled.

`frontend` waits on `backend: service_healthy`.

## Images

**Backend** — `python:3.12-slim`. Dependencies installed before the source is
copied, so a code change does not invalidate the dependency layer. Runs as uid
10001. No build toolchain in the final image.

**Frontend** — three stages (deps → build → runner) on `node:22-alpine`. Uses
Next's `output: 'standalone'`, so the runtime image carries only the traced
dependencies. Runs as uid 10001.

`NEXT_PUBLIC_*` values are **inlined at build time**, so they are build args in
compose. Changing `NEXT_PUBLIC_API_BASE_URL` requires a rebuild — that is how
Next works, not an oversight.

## Scaling

**Workers** scale horizontally:

```bash
docker compose up -d --scale worker=4
```

Task claiming is a conditional `UPDATE`, so two workers cannot execute the same
task. `advance()` takes a row lock on the run, so concurrent finishers serialise
their scheduling decisions.

**API** containers are stateless; run as many as needed behind a load balancer.

**Concurrency limits.** `MAX_PARALLEL_INVESTIGATIONS` bounds in-flight
investigations *per run* — the knob to tune against a provider's rate limits.
`WORKER_CONCURRENCY` bounds each worker's process pool.

**PostgreSQL** is the single stateful component. The connection pool is
`DB_POOL_SIZE + DB_MAX_OVERFLOW` per process; budget
`(api_replicas + worker_replicas) × (pool + overflow)` against
`max_connections`.

## Operational notes

**Readiness vs liveness.** `/health/live` deliberately touches nothing, so a
database blip does not get the container killed. `/health/ready` requires the
database. `/health` reports every dependency and returns `503` when degraded.

**Statement timeout.** Every connection sets
`statement_timeout = DB_STATEMENT_TIMEOUT_MS` (30s), so a pathological plan
cannot pin a worker indefinitely.

**Stale task recovery.** A `RUNNING` task whose worker vanished is returned to
`RETRYING` after `STALE_TASK_TIMEOUT_SECONDS` (900s) on the next `advance()`, or
failed if out of budget. A killed worker cannot strand a run.

**Redis is not durable state.** Losing Redis loses in-flight queue entries. The
task graph and every status live in PostgreSQL, so a stuck run recovers through
stale-task reclamation. It is not a data-loss event.

**Logs** are JSON on stdout — ready for any aggregator. Filter by `run_id` to
reconstruct a whole investigation, including every tool call and LLM call.

**Backups.** PostgreSQL holds everything. Back it up with PITR. The synthetic
dataset is regenerable from `SEED_RANDOM_SEED`, but runs, evidence, claims,
reports and the audit trail are not.

## Configuration

Everything from the environment; see `.env.example`. The defaults run the whole
platform with no credentials, which is what makes a cold start work.

Two safety behaviours:

- `LLM_PROVIDER=openai` with no key logs a warning and uses the deterministic
  provider rather than failing at the first agent call.
- `APP_ENV=production` hard-disables failure injection regardless of the rates.

## Migrations in a deployment

```bash
docker compose run --rm migrate              # or
docker compose exec backend alembic upgrade head
```

Forward-only in practice, though `downgrade` is implemented for both revisions.
Deploy order: migrate → API/workers. The schema changes so far are additive or
constraint-only, so a brief version skew is tolerable.

## What is deliberately not here

- **Kubernetes manifests.** Compose is the documented target; the images are
  plain and portable.
- **A CI pipeline.** `make check` is exactly what CI would run.
- **Managed-service wiring.** `DATABASE_URL` and `REDIS_URL` point anywhere.
