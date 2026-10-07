# Atlas — reliable agentic systems

Atlas is a small, runnable reference implementation of an agent platform for complex, evidence-backed work. It turns a natural-language objective into a visible workflow:

`Plan → Retrieve → Investigate → Verify → Report`

The repository includes:

- FastAPI endpoints for creating runs, streaming structured events, approving sensitive actions, and reading the final report.
- An async workflow runner with retries, checkpoints, human approval, and a deterministic demo mode.
- A responsive operations console for reviewing active runs, trace events, evidence, and agent health.
- Docker and docker-compose files for running the API and static console together.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

Open http://localhost:8000.

To use Docker:

```bash
docker compose up --build
```

The demo workflow is intentionally self-contained. Integrations are represented by adapters in `backend/main.py`; replace those functions with PostgreSQL, pgvector, REST, or Neo4j clients as the platform moves beyond the demo.

## API surface

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/api/runs` | Start an objective |
| `GET` | `/api/runs/{run_id}` | Read run state, nodes, events, evidence, and report |
| `POST` | `/api/runs/{run_id}/approve` | Release a pending sensitive action |
| `GET` | `/api/health` | Service health and agent counts |

## Production direction

The workflow boundary is deliberately explicit. A production deployment can replace the in-process queue with Celery/Redis or Temporal, persist `RunState` and events in PostgreSQL, and add OpenTelemetry exporters without changing the frontend contract.
