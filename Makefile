# Veriflow — developer commands.
#
# Everything here is expected to work from a clean checkout. `make setup`
# prepares both toolchains; `make up` brings the whole stack up in Docker.

SHELL := /bin/bash
.DEFAULT_GOAL := help

VENV        := .venv
PY          := $(VENV)/bin/python
PIP         := $(VENV)/bin/pip
BACKEND     := backend
FRONTEND    := frontend
COMPOSE     := docker compose
PYTHON_BIN  ?= python3.11

# Host-side database URLs (compose publishes postgres on 5433 by default).
export DATABASE_URL      ?= postgresql+psycopg://veriflow:veriflow@localhost:5433/veriflow
export TEST_DATABASE_URL ?= postgresql+psycopg://veriflow:veriflow@localhost:5433/veriflow_test
export REDIS_URL         ?= redis://localhost:6380/0

.PHONY: help
help: ## Show this help
	@echo "Veriflow — make targets"
	@echo
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "Typical first run:  make setup && make up && make migrate && make seed"

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

.PHONY: setup
setup: .env $(VENV) frontend-install ## Create .env, the Python venv and install all dependencies
	@echo "Setup complete. Next: make up && make migrate && make seed"

.env:
	@cp -n .env.example .env && echo "Created .env from .env.example"

$(VENV):
	$(PYTHON_BIN) -m venv $(VENV)
	$(PIP) install --quiet --upgrade pip
	$(PIP) install --quiet -r $(BACKEND)/requirements-dev.txt
	@echo "Python environment ready ($$($(PY) --version))"

.PHONY: frontend-install
frontend-install: ## Install frontend dependencies
	cd $(FRONTEND) && npm install

# ---------------------------------------------------------------------------
# Docker stack
# ---------------------------------------------------------------------------

.PHONY: up
up: .env ## Build and start the full stack (postgres, redis, migrate, api, worker, frontend)
	$(COMPOSE) up --build -d
	@$(MAKE) --no-print-directory wait
	@echo
	@echo "  Frontend  http://localhost:3000"
	@echo "  API docs  http://localhost:8000/docs"
	@echo "  Health    http://localhost:8000/health"
	@echo
	@echo "The database is empty until you run: make seed"

.PHONY: up-deps
up-deps: .env ## Start only postgres and redis (for local backend development)
	$(COMPOSE) up -d postgres redis
	@$(MAKE) --no-print-directory wait-deps

.PHONY: down
down: ## Stop the stack (volumes are preserved)
	$(COMPOSE) down

.PHONY: wait-deps
wait-deps: ## Block until postgres and redis are healthy
	@printf "Waiting for postgres and redis"
	@for i in $$(seq 1 60); do \
		if $(COMPOSE) exec -T postgres pg_isready -U veriflow -d veriflow >/dev/null 2>&1 \
			&& $(COMPOSE) exec -T redis redis-cli ping >/dev/null 2>&1; then \
			echo " ready"; exit 0; fi; \
		printf "."; sleep 2; \
	done; echo; echo "ERROR: dependencies did not become healthy"; exit 1

.PHONY: wait
wait: wait-deps ## Block until the API is healthy
	@printf "Waiting for the API"
	@for i in $$(seq 1 60); do \
		if curl -fsS http://localhost:8000/health/ready >/dev/null 2>&1; then echo " ready"; exit 0; fi; \
		printf "."; sleep 2; \
	done; echo; echo "ERROR: the API did not become ready"; $(COMPOSE) logs --tail=40 backend; exit 1

.PHONY: logs
logs: ## Tail logs from every service
	$(COMPOSE) logs -f --tail=100

.PHONY: logs-worker
logs-worker: ## Tail worker logs only
	$(COMPOSE) logs -f --tail=100 worker

.PHONY: ps
ps: ## Show service status
	$(COMPOSE) ps

.PHONY: shell-db
shell-db: ## Open psql against the running database
	$(COMPOSE) exec postgres psql -U veriflow -d veriflow

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

.PHONY: migrate
migrate: ## Apply database migrations (runs inside the stack when it is up)
	@if $(COMPOSE) ps --status running --services 2>/dev/null | grep -q '^backend$$'; then \
		$(COMPOSE) exec -T backend alembic upgrade head; \
	else \
		cd $(BACKEND) && ../$(PY) -m alembic upgrade head; \
	fi

.PHONY: migrate-down
migrate-down: ## Roll back the most recent migration
	cd $(BACKEND) && ../$(PY) -m alembic downgrade -1

.PHONY: migration
migration: ## Generate a migration from model changes (make migration m="add x")
	cd $(BACKEND) && ../$(PY) -m alembic revision --autogenerate -m "$(m)"

.PHONY: seed
seed: ## Generate the synthetic dataset (3,000 customers; idempotent)
	@if $(COMPOSE) ps --status running --services 2>/dev/null | grep -q '^backend$$'; then \
		$(COMPOSE) exec -T backend python -m app.seed.cli; \
	else \
		cd $(BACKEND) && ../$(PY) -m app.seed.cli; \
	fi

.PHONY: reseed
reseed: ## Delete and regenerate the synthetic dataset
	@if $(COMPOSE) ps --status running --services 2>/dev/null | grep -q '^backend$$'; then \
		$(COMPOSE) exec -T backend python -m app.seed.cli --reset; \
	else \
		cd $(BACKEND) && ../$(PY) -m app.seed.cli --reset; \
	fi

# ---------------------------------------------------------------------------
# Local development (outside Docker)
# ---------------------------------------------------------------------------

.PHONY: dev-api
dev-api: ## Run the API locally with reload (needs make up-deps)
	cd $(BACKEND) && ../$(VENV)/bin/uvicorn app.main:app --reload --port 8000

.PHONY: dev-worker
dev-worker: ## Run a Celery worker locally (needs make up-deps)
	cd $(BACKEND) && ../$(VENV)/bin/celery -A app.workers.celery_app:celery_app worker --loglevel=info -Q veriflow

.PHONY: dev-frontend
dev-frontend: ## Run the frontend dev server
	cd $(FRONTEND) && npm run dev

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

.PHONY: test
test: ## Run the whole backend test suite
	cd $(BACKEND) && ../$(PY) -m pytest

.PHONY: test-unit
test-unit: ## Run unit tests only (no database required)
	cd $(BACKEND) && ../$(PY) -m pytest -m unit

.PHONY: test-integration
test-integration: ## Run integration tests (requires postgres + pgvector)
	cd $(BACKEND) && ../$(PY) -m pytest -m integration

.PHONY: test-agents
test-agents: ## Run agent tests against the deterministic provider
	cd $(BACKEND) && ../$(PY) -m pytest -m agents

.PHONY: test-e2e
test-e2e: ## Run end-to-end workflow scenarios
	cd $(BACKEND) && ../$(PY) -m pytest -m e2e

.PHONY: test-cov
test-cov: ## Run the suite with a coverage report
	cd $(BACKEND) && ../$(PY) -m pytest --cov=app --cov-report=term-missing --cov-report=html

.PHONY: test-frontend
test-frontend: typecheck-frontend lint-frontend build-frontend ## Frontend checks: types, lint, production build

# ---------------------------------------------------------------------------
# Quality
# ---------------------------------------------------------------------------

.PHONY: lint
lint: lint-backend lint-frontend ## Lint everything

.PHONY: lint-backend
lint-backend: ## Ruff check
	cd $(BACKEND) && ../$(VENV)/bin/ruff check .

.PHONY: lint-frontend
lint-frontend: ## ESLint
	cd $(FRONTEND) && npm run lint

.PHONY: format
format: ## Format backend and frontend sources
	cd $(BACKEND) && ../$(VENV)/bin/ruff format . && ../$(VENV)/bin/ruff check --fix .

.PHONY: typecheck
typecheck: typecheck-backend typecheck-frontend ## Type-check everything

.PHONY: typecheck-backend
typecheck-backend: ## mypy
	cd $(BACKEND) && ../$(VENV)/bin/mypy

.PHONY: typecheck-frontend
typecheck-frontend: ## tsc --noEmit
	cd $(FRONTEND) && npm run typecheck

.PHONY: build-frontend
build-frontend: ## Production build of the frontend
	cd $(FRONTEND) && npm run build

.PHONY: check
check: lint typecheck test ## Everything CI would run

# ---------------------------------------------------------------------------
# Evaluation and demo
# ---------------------------------------------------------------------------

.PHONY: evaluate
evaluate: ## Run the evaluation harness and print the metrics
	@if $(COMPOSE) ps --status running --services 2>/dev/null | grep -q '^backend$$'; then \
		$(COMPOSE) exec -T backend python -m app.evaluation.cli; \
	else \
		cd $(BACKEND) && ../$(PY) -m app.evaluation.cli; \
	fi

.PHONY: demo
demo: ## Submit the demo objective and follow it to completion
	cd $(BACKEND) && ../$(PY) -m app.demo

.PHONY: health
health: ## Print the API health payload
	@curl -fsS http://localhost:8000/health | $(PY) -m json.tool

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

.PHONY: clean
clean: ## Remove build artefacts and caches (keeps .env and volumes)
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -prune -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -prune -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf $(BACKEND)/htmlcov $(BACKEND)/.coverage
	rm -rf $(FRONTEND)/.next
	@echo "Cleaned."

.PHONY: clean-all
clean-all: clean ## Also remove the venv, node_modules and Docker volumes (destroys data)
	$(COMPOSE) down -v
	rm -rf $(VENV) $(FRONTEND)/node_modules
	@echo "Removed the virtualenv, node_modules and Docker volumes."
