# Cogniflow — reliable agentic systems

Cogniflow is an agent platform for complex, evidence-backed work. It turns a natural-language objective into a visible workflow:

`Plan → Retrieve → Investigate → Verify → Report`

The local environment includes:

- FastAPI orchestration endpoints for creating runs, structured state, and human approval.
- PostgreSQL persistence for accounts, activity, support threads, contracts, runs, events, and evidence.
- 60 deterministic synthetic customer accounts seeded automatically on first boot.
- pgvector-ready PostgreSQL for future semantic embeddings and vector retrieval.
- A responsive operations console for reviewing workflow, trace events, and evidence.
- Docker Compose for starting Cogniflow and PostgreSQL together.

## Run the full customer-data demo

```bash
docker compose up --build
```

Open http://localhost:8000. The first database startup seeds synthetic data automatically. Inspect it with:

```bash
docker compose exec postgres psql -U cogniflow -d cogniflow
```

Example query:

```sql
SELECT name, health_score, segment FROM customer_accounts ORDER BY health_score ASC LIMIT 10;
```

## Run the API without PostgreSQL

Without `DATABASE_URL`, Cogniflow uses a temporary demo fallback and data is lost when the process stops.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

## API surface

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/api/runs` | Start an objective |
| `GET` | `/api/runs/{run_id}` | Read run state, events, evidence, and report |
| `POST` | `/api/runs/{run_id}/approve` | Release a pending sensitive action |
| `GET` | `/api/health` | Service and database health |

## Production direction

The schema and workflow boundary are explicit so this demo can evolve into a customer product. Next production layers are authentication and tenant isolation, real LLM/tool adapters, pgvector embeddings, a Redis/Celery or Temporal worker, OpenTelemetry tracing, migrations, backups, and managed PostgreSQL.

## Cogniflow architecture

```text
User objective
      ↓
FastAPI API
      ↓
Planner → structured ExecutionPlan (tasks + dependencies)
      ↓
Workflow runner
   ┌──┼─────────────┐
   ↓  ↓             ↓
SQL  RAG       External APIs
agent agent         agent
   └──┼─────────────┘
      ↓
Risk screening → parallel account investigations
      ↓
Claim-level verifier → supported / rejected claims
      ↓
Report generator → human approval gate → final report
```

## Synthetic customer dataset

The PostgreSQL seed creates 3,000 fictional SaaS accounts with structured and unstructured signals:

- `customer_accounts`, `subscriptions`, and `product_usage`
- `support_tickets`, `support_threads`, and `customer_documents`
- `payments`, `nps_surveys`, and `customer_outcomes`
- historical `CHURNED` and `RENEWED` outcomes for future evaluation

The first version uses deterministic tool adapters, so results are reproducible. The database is ready for replacing the document text with real embeddings and pgvector similarity search.

## Workflow state

Each run stores its objective, structured plan, task dependencies, task status, retry counters, events, claims, evidence, report, and approval state. This gives `GET /api/runs/{run_id}` enough information to reconstruct what happened instead of returning only the final answer.
