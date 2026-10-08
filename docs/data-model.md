# Data model

21 tables, all created by Alembic migrations. `create_all` is never used as the
migration mechanism.

Enums are stored as text with `CHECK` constraints rather than PostgreSQL `ENUM`
types: adding a value is a constraint change instead of a type migration, and
values stay readable in `psql`.

## Customer domain

### `customers`
`id` · `external_id` (unique) · `company_name` · `industry` · `country` ·
`company_size` · `employee_count` · `account_tier` · `account_manager` ·
`scenario_persona` · timestamps

`CHECK` on `account_tier` and `employee_count >= 0`. Indexes on
`account_tier`, `company_name`, and composite `(account_tier, company_name)`.

`scenario_persona` labels the synthetic generator's scenario. It is used by the
seed and the evaluation harness and is **never exposed to an agent as a
feature** — it would leak the answer.

### `subscriptions`
One per customer (`customer_id` unique). `plan` ·
`monthly_recurring_revenue` · `annual_contract_value` · `contract_start` ·
`contract_end` · `renewal_date` · `subscription_status` · `seats_purchased`

`CHECK`: MRR ≥ 0, seats ≥ 0, `contract_end >= contract_start`. Composite index
`(renewal_date, subscription_status)` — the candidate-selection query.

### `product_usage`
`usage_date` · `active_users` · `total_logins` · `sessions` ·
`projects_created` · `api_calls` · `feature_adoption_score` · `seats_active`

Unique `(customer_id, usage_date)`; index `(customer_id, usage_date)`.

### `support_tickets`
`external_ticket_id` (unique) · `created_at` · `resolved_at` · `category` ·
`priority` · `status` · `resolution_hours` · `csat_score` · `subject` ·
`description`

`CHECK` on priority, status, and `csat_score` between 1 and 5 **or null** —
most tickets have no CSAT response, which the analytics layer must tolerate.

### `payments`
`invoice_date` · `due_date` *(nullable on purpose)* · `amount` ·
`payment_date` · `payment_status` · `days_overdue`

`due_date` is nullable because real billing exports contain invoices without
one. The analytics layer treats the *status* as authoritative and the date as
best-effort.

### `nps_surveys`
`response_date` · `score` (`CHECK` 0–10) · `feedback`

### `customer_documents`
`source_type` · `title` · `source_date` · `content` · `metadata` (JSONB)

### `document_chunks`
`document_id` · `customer_id` *(denormalised)* · `chunk_index` · `content` ·
`embedding vector(1536)` · `metadata`

`customer_id` is denormalised so vector search filters by customer **without a
join** — the filter is a hard SQL predicate, not a post-filter.

```sql
CREATE INDEX ix_document_chunks_embedding_hnsw
  ON document_chunks USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);
```

### `customer_outcomes`
One per customer. `outcome` (CHURNED / RENEWED / DOWNGRADED / EXPANDED /
UNKNOWN) · `outcome_date` · `churn_reason` · `notes`

The evaluation label. The risk engine never reads this table.

## Workflow

### `runs`
`objective` · `workflow_type` · `workflow_mode` · `status` · `progress`
(`CHECK` 0–100) · `current_stage` · `created_at` / `started_at` /
`completed_at` / `failed_at` · `error_message` · `created_by` ·
`metadata` (JSONB)

`metadata` carries resolved parameters, the plan snapshot, the risk ranking,
verification stats and token/cost counters.

### `run_tasks`
`task_key` · `agent_type` · `description` · `stage` · `status` ·
`dependencies` (JSONB) · `input_payload` · `output_payload` · `retry_count` ·
`max_retries` · `error_message` · `dispatch_token` · timestamps ·
`duration_ms`

Unique `(run_id, task_key)`. Index `(run_id, status)`.

### `evidence`
`customer_id` · `source_type` · `source_id` · `reference` · `title` ·
`content` · `source_date` · `relevance_score` · `metadata`

- Unique `(run_id, customer_id, source_id)` — makes the write idempotent.
- Unique `(run_id, customer_id, reference)` — the reference namespace.

References are allocated **per customer**. Per-run numbering raced under
parallel workers: two concurrent investigations read the same count and both
inserted the same `EV-n`. One customer is investigated by exactly one task, so
per-customer numbering needs no lock — and reads better. Migration `0002`
records this change.

### `claims`
`customer_id` · `claim_key` · `claim_text` · `claim_type` · `status` ·
`confidence` (`CHECK` 0–1) · `verification_reason` · `suggested_revision` ·
`final_text` · `verified_at`

Unique `(run_id, claim_key)`. `final_text` is the text the report may use — null
for rejected claims, which is how exclusion is enforced at the data layer.

### `claim_evidence`
Many-to-many, both sides `ON DELETE CASCADE`.

### `investigations`
`risk_score` (`CHECK` 0–100) · `heuristic_risk_score` · `risk_level` ·
`confidence` · `summary` · `risk_factors` · `quantitative_signals` ·
`recommended_actions` · `data_gaps`

Unique `(run_id, customer_id)`. Keeping both the heuristic and the final score
makes the LLM's adjustment visible and auditable.

### `reports`
One per run. `title` · `executive_summary` · `report_payload` (JSONB) ·
`markdown_content`

### `approvals`
`customer_id` · `action_type` · `proposed_action` · `action_payload` ·
`status` · `reason` · `idempotency_key` · `requested_at` · `reviewed_at` ·
`reviewed_by` · `reviewer_comment`

Unique `(run_id, idempotency_key)` — a retried task cannot open a second
identical request.

### `audit_events`
`run_id` · `task_id` · `customer_id` · `event_type` · `actor_type` ·
`actor_id` · `message` · `payload` · `trace_id` · `created_at`

25 event types covering run and task lifecycle, plan creation and rejection,
tool and LLM calls, evidence and claim recording, verification verdicts,
investigation completion, report generation, approval request/grant/reject,
prompt-injection detection and validation failures.

### `llm_calls`
`agent` · `provider` · `model` · `operation` · `prompt_tokens` ·
`completion_tokens` · `latency_ms` · `estimated_cost_usd` · `attempts` ·
`valid_output`

### `evaluation_runs`
`name` · `status` · `dataset_description` · `parameters` · `metrics` ·
`details` · `error_message` · `duration_ms`

## Avoiding N+1

`CustomerRepository.load_bundles(ids)` issues **five queries regardless of how
many customers are screened** — one for customers (with `selectinload` for
subscription and outcome) and one each for usage, tickets, payments and surveys,
grouped in Python. The naive per-customer version would issue 5N. An integration
test counts the statements and asserts the number is constant.

## Migrations

| Revision | Contents |
|---|---|
| `0001_initial_schema` | All 21 tables, constraints, indexes, `CREATE EXTENSION vector`, the HNSW index |
| `0002_scope_evidence_refs` | Evidence reference uniqueness moved to `(run_id, customer_id, reference)` |

`0002` is hand-written: `--autogenerate` does not know about the HNSW index
(raw SQL in `0001`) and would propose dropping it.

Both directions are implemented, and the integration suite applies the
migrations from an empty database on every session — so the migrations are
themselves under test.
