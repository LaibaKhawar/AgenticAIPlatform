# Implementation status

Requirement-by-requirement audit against the project brief.
**Last verified:** full stack rebuilt from empty volumes, migrated, seeded,
demo run executed through real Celery workers, evaluation run, 479 tests
passing, ruff + mypy + tsc + eslint clean, frontend production build green.

Legend: **✅ implemented** · **◐ partial** (scope stated) · **✗ not implemented**
(reason stated)

---

## Core capabilities

| Capability | Status | Where |
|---|---|---|
| LLM agents | ✅ | 7 declared agents, `app/agents/` |
| Task planning | ✅ | `PlannerAgent` → validated `ExecutionPlan` |
| Typed structured outputs | ✅ | Pydantic at every model boundary, `app/schemas/agent.py` |
| Tool calling | ✅ | 12-tool registry with permissions, `app/tools/` |
| Task dependency DAG | ✅ | `app/orchestration/dag.py` — validation, cycles, topo order, readiness |
| Workflow orchestration | ✅ | `app/orchestration/engine.py` |
| Persistent state | ✅ | 21 PostgreSQL tables |
| PostgreSQL | ✅ | 16 via `pgvector/pgvector:pg16` |
| pgvector | ✅ | `vector(1536)` + HNSW cosine index |
| Semantic retrieval / RAG | ✅ | chunk → embed → store → query, `app/rag/` |
| Evidence attribution | ✅ | chunk id, document id, source type/date, relevance, customer |
| Deterministic analytics | ✅ | `app/analytics/metrics.py`, `risk.py` |
| Claim verification | ✅ | 3-stage pipeline, `app/agents/verifier.py` |
| Hallucination mitigation | ✅ | id validation + rules + rule-capped model |
| Human-in-the-loop | ✅ | deterministic policy, parked runs, resume |
| Asynchronous execution | ✅ | `POST /runs` → 202; Celery workers |
| Concurrency | ✅ | bounded fan-out via the persisted graph |
| Celery | ✅ | `app/workers/` |
| Redis | ✅ | broker + result backend |
| Retries | ✅ | exponential backoff + full jitter, typed classification |
| Idempotency | ✅ | natural unique keys; conditional task claiming |
| Failure handling | ✅ | taxonomy, skip propagation, tolerated fan-out failures |
| Audit trails | ✅ | `audit_events`, 25 event types |
| Observability | ✅ | JSON logs + OTEL spans + per-call metering |
| Tracing | ✅ | OpenTelemetry, 11 span names |
| Evaluation | ✅ | real harness, `app/evaluation/` |
| Frontend product design | ✅ | 11 routes, Next.js 15 |
| Docker deployment | ✅ | 6 compose services, health-gated |
| Testing | ✅ | 479 tests across 4 layers |

---

## Database

All 15 specified tables plus 6 more (`run_tasks`, `claim_evidence`,
`audit_events`, `llm_calls`, `evaluation_runs`, `reports`). Every specified
column present. Indexes, `CHECK` constraints, explicit FK `ON DELETE` behaviour,
and natural unique keys for idempotency. Alembic migrations only — ✅

`CUSTOMER_OUTCOMES` supports all five outcomes — ✅

---

## Synthetic data

| Requirement | Target | Actual | Status |
|---|---|---|---|
| Customers | ~3,000 | 3,000 | ✅ |
| Historical churned | ~450 | 450 | ✅ |
| Renewed | ~2,200 | 2,147 | ✅ |
| Remaining active/current | — | 301 live + 102 downgraded/expanded | ✅ |
| Hundreds with upcoming renewals | hundreds | 252 within 90 days | ✅ |
| Deterministic seeding | — | verified identical across reseeds | ✅ |
| Correlated, not independent | — | 12 personas drive signals jointly | ✅ |
| 12 named personas | 12 | 12 | ✅ |
| Realistic noise | — | multiplicative jitter + probabilistic outcomes | ✅ |
| Document types | 7 | 7 source types, 29 themes | ✅ |
| Ambiguous evidence | — | ✅ | ✅ |
| Contradictory signals | — | healthy-with-negative / risky-with-positive | ✅ |
| Healthy accounts with negative signals | — | ✅ | ✅ |
| Risk accounts that look healthy quantitatively | — | `QUIET_DISENGAGEMENT` | ✅ |
| No LLM calls to seed | — | fully templated | ✅ |
| Batched / practical | — | bulk inserts, ~17s | ✅ |

**Demo account** `CUST-000001` Acme Corp — every specified characteristic
pinned: Enterprise, $8,200 MRR, renewal ~31 days, DAU 82→43, tickets 3→11, NPS
8→3, invoice 38 days overdue, competitor email, CSM note naming Competitor X and
pricing/reporting concerns. Scores **96.2 CRITICAL**. "Evaluating alternatives"
→ SUPPORTED; "has decided to cancel" → **CONTRADICTED** — ✅

---

## Deterministic risk engine

All 11 specified functions implemented in `app/analytics/metrics.py` and
`risk.py`: `calculate_usage_change`, `calculate_active_user_change`,
`calculate_ticket_growth`, `calculate_average_csat`,
`calculate_payment_delinquency`, `get_latest_nps`, `days_until_renewal`,
`calculate_seat_utilization`, `find_recent_critical_tickets`,
`find_customers_renewing_within`, plus `calculate_feature_adoption_change`.

Formula documented in code, in `docs/agents.md`, and exposed at
`GET /api/v1/system`. Explicitly labelled **not a trained predictive model**.
Used for candidate generation and ranking; the LLM may adjust by at most ±15
points — ✅

---

## Tools, agents, API

**Tool registry** — all 11 required tools plus `propose_customer_action`. Each
declares name, description, input model, output model, permissions, read/write
class, timeout, retry policy. No arbitrary SQL; all inputs validated — ✅

**Agents** — base agent with name, role, allowed tools, model settings, prompt,
output schema, timeout, retries, tracing. Planner, data, retrieval,
investigator, verifier, reporter all per spec, plus risk and policy — ✅

**API** — all 21 specified endpoints, plus 12 more. Pagination on every
collection, proper 404s, structured validation errors, working OpenAPI — ✅

---

## Required structured types

`ExecutionPlan` · `TaskDefinition` · `EvidenceItem` · `RiskSignalModel` ·
`RiskFactor` · `ClaimDraft` · `ClaimVerification` · `InvestigationResult` ·
`RecommendedAction` · `FinalReport` — all ✅, plus `VerificationBatch`,
`ReportNarrative`, `ReportAccountSection`.

Invalid output: logged, re-prompted with the validation error, retry-limited,
then fails the task clearly. Never silently accepted — ✅

---

## Frontend

All 7 required nav items. Dashboard shows all 11 required values from real data.
Objective composer with the default example and all 4 structured controls. Run
detail shows all 9 stages and all 8 states with task name, agent, dependencies,
duration, retry count, status and error. Customer list and detail with every
specified aggregate. Investigation results with risk score, level, confidence,
quantitative signals, qualitative evidence, verified/rejected claims,
recommended actions and approval requirements. Evidence cards show source type,
date, original content and relevance. Report with all 10 required sections,
stored as JSON + Markdown, rendered elegantly. Approvals with approve, reject
and reviewer comment — ✅

All required UX states present: loading skeletons, empty states with next
actions, failing-stage display, retry state, explicit "insufficient evidence",
valid no-high-risk report, partial-data continuation — ✅

liquid-glass-js inspected, vendored and used carefully on one surface with
documented reasoning — ✅ (see `docs/frontend.md`)

PDF export — ✗ *optional in the brief; Markdown download implemented instead.*

---

## Testing

| Required | Status |
|---|---|
| Unit: risk calcs, usage decline, support spike, NPS, missing metrics, null data, zero seats, no tickets, no payments | ✅ |
| Unit: DAG validation, cycles, duplicate tasks, unknown agents | ✅ |
| Unit: retry classification, retry exhaustion | ✅ |
| Unit: structured validation, permission boundaries, sensitive-action policy, evidence reference validation, report filtering | ✅ |
| Integration: repositories, migrations, pgvector insert/search, metadata filtering, API paths, run/task persistence, workflow execution, retries, evidence/claim/verification storage, report generation, approval pause/resume, cancellation | ✅ |
| Agents: valid planner, malformed planner, circular DAG, investigator result, missing evidence, hallucinated id, verifier supported/unsupported/contradiction/revision, reporter excludes rejected, prompt injection | ✅ |
| E2E scenarios A–F | ✅ |
| Real PostgreSQL/pgvector, not mocked | ✅ |
| No live LLM required | ✅ |
| Asserts business behaviour, not `status_code == 200` | ✅ |

Tests written alongside each phase, not deferred. Two concurrency bugs found by
running the real stack are now covered by regression tests
(`tests/integration/test_concurrency.py`).

---

## Quality, Docker, docs

Ruff clean, mypy clean (78 files), `tsc --noEmit` clean, ESLint clean, frontend
production build green. No global suppressions — ✅

Dockerfiles for backend, frontend and worker (worker shares the backend image —
same code, different command). Compose services for all six with health checks
and dependency ordering. Migrations are a one-shot service, so there is no
startup race. `docker compose up --build` brings the stack up — ✅

`.env.example` complete, no secrets committed, sensible defaults — ✅

Makefile: all 13 required targets plus 20 more, all verified working — ✅

README with all 19 required sections and Mermaid diagrams; 8 docs under
`docs/` — ✅

---

## Deliberately not implemented

| Item | Why |
|---|---|
| Kubernetes | Explicitly excluded by the brief |
| Neo4j on the critical path | Explicitly excluded |
| Temporal in V1 | Explicitly excluded; `Executor` interface leaves room |
| Microservice per agent, event sourcing, Kafka, custom vector DB, self-hosted models, advanced RBAC | Explicitly listed as over-engineering |
| PDF export | Optional, and only after the core works |
| SSE/WebSockets | Brief says "whichever is reliable and simplest" — polling is both at this scale |

---

## Known gaps

Stated plainly rather than hidden:

1. **Single tenant.** No tenant isolation or row-level security.
2. **Development auth.** API-key boundary, not an identity platform. No users,
   roles or sessions.
3. **Local embeddings are not semantic.** Deterministic hashed bag-of-features
   for development and CI; use `EMBEDDING_PROVIDER=openai` for real retrieval
   quality.
4. **Verification figures under the fake provider measure the deterministic
   rules**, not a frontier model's judgement.
5. **Claim rules are lexical.** They catch the dominant failure mode and will
   miss paraphrase. A floor under the model, not a replacement.
6. **All metrics are synthetic-data results.**
7. **No cross-account retrieval**, no scheduled runs, no PDF export.

---

## Verification log

Commands run against a clean environment, in order:

```
docker compose down -v                    # empty volumes
docker compose up -d --build              # 6 services, all healthy
docker compose logs migrate               # 0001 → 0002 applied
curl /health                              # status ok, pgvector true, redis ok
docker compose exec backend python -m app.seed.cli
                                          # 3,000 customers in 16.3s
curl -X POST /api/v1/runs                 # 202, status QUEUED
                                          # → WAITING_FOR_APPROVAL via Celery
                                          # 5 accounts investigated in parallel
curl /api/v1/runs/{id}/investigations      # Acme 96.2 CRITICAL, 9 claims
                                          # "decided to cancel" → CONTRADICTED
POST /approvals/{id}/reject  (×1)         # mixed decisions
POST /approvals/{id}/approve (×3)
curl /api/v1/runs/{id}                    # COMPLETED, progress 100
docker compose exec backend python -m app.demo
                                          # COMPLETED, 5 investigations,
                                          # 46 evidence, 33 claims, 8 approvals
docker compose exec backend python -m app.evaluation.cli
                                          # AUC 0.841, scope precision 1.000,
                                          # 0 rejected claims leaked
make test                                 # 479 passed
make lint && make typecheck               # clean
cd frontend && npm run build              # 12 routes built
```

Database integrity after the full test suite: the development database retains
its 3,000 customers — the suite refuses to truncate anything but a `*_test`
database.
