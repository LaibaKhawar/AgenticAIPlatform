from __future__ import annotations

import json
import os
from datetime import date, timedelta
from typing import Any

import asyncpg


SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS customer_accounts (
    id SERIAL PRIMARY KEY,
    external_id TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    segment TEXT NOT NULL,
    plan TEXT NOT NULL,
    owner TEXT NOT NULL,
    health_score NUMERIC(5, 2) NOT NULL,
    risk_score NUMERIC(5, 4) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE customer_accounts ADD COLUMN IF NOT EXISTS risk_score NUMERIC(5, 4) NOT NULL DEFAULT 0;
CREATE TABLE IF NOT EXISTS subscriptions (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES customer_accounts(id) ON DELETE CASCADE,
    plan TEXT NOT NULL,
    monthly_revenue INTEGER NOT NULL,
    contract_start DATE NOT NULL,
    contract_end DATE NOT NULL,
    renewal_date DATE NOT NULL,
    status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS product_usage (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES customer_accounts(id) ON DELETE CASCADE,
    usage_date DATE NOT NULL,
    active_users INTEGER NOT NULL,
    sessions INTEGER NOT NULL,
    features_used INTEGER NOT NULL,
    api_calls INTEGER NOT NULL,
    projects_created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS support_tickets (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES customer_accounts(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    category TEXT NOT NULL,
    priority TEXT NOT NULL,
    status TEXT NOT NULL,
    resolution_hours INTEGER NOT NULL,
    csat_score NUMERIC(3, 1)
);
CREATE TABLE IF NOT EXISTS payments (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES customer_accounts(id) ON DELETE CASCADE,
    invoice_date DATE NOT NULL,
    amount INTEGER NOT NULL,
    payment_date DATE,
    payment_status TEXT NOT NULL,
    days_overdue INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS nps_surveys (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES customer_accounts(id) ON DELETE CASCADE,
    survey_date DATE NOT NULL,
    score INTEGER NOT NULL,
    feedback TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS customer_documents (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES customer_accounts(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    source_name TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding vector(3),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS customer_outcomes (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES customer_accounts(id) ON DELETE CASCADE,
    outcome TEXT NOT NULL,
    outcome_date DATE NOT NULL,
    reason TEXT
);
CREATE TABLE IF NOT EXISTS customer_activity (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES customer_accounts(id) ON DELETE CASCADE,
    period_start DATE NOT NULL,
    active_users INTEGER NOT NULL,
    sessions INTEGER NOT NULL,
    usage_change NUMERIC(5, 2) NOT NULL
);
CREATE TABLE IF NOT EXISTS support_threads (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES customer_accounts(id) ON DELETE CASCADE,
    subject TEXT NOT NULL,
    content TEXT NOT NULL,
    sentiment NUMERIC(4, 2) NOT NULL,
    resolved BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS contracts (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES customer_accounts(id) ON DELETE CASCADE,
    renewal_date DATE NOT NULL,
    annual_value INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    objective TEXT NOT NULL,
    status TEXT NOT NULL,
    approval_mode TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    current_node TEXT NOT NULL,
    state JSONB NOT NULL DEFAULT '{}'::jsonb,
    report JSONB,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS run_events (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    message TEXT NOT NULL,
    agent TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS run_evidence (
    id SERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    confidence NUMERIC(5, 4) NOT NULL,
    excerpt TEXT NOT NULL,
    tag TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS run_tasks (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    agent TEXT NOT NULL,
    description TEXT NOT NULL,
    dependencies JSONB NOT NULL DEFAULT '[]'::jsonb,
    status TEXT NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    output JSONB
);
CREATE TABLE IF NOT EXISTS run_claims (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    claim TEXT NOT NULL,
    verification_status TEXT NOT NULL,
    confidence NUMERIC(5, 4) NOT NULL,
    evidence_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    reason TEXT NOT NULL
);
"""


async def connect() -> asyncpg.Pool | None:
    url = os.getenv("DATABASE_URL")
    if not url:
        return None
    for _ in range(20):
        try:
            pool = await asyncpg.create_pool(url, min_size=1, max_size=5)
            async with pool.acquire() as conn:
                await conn.execute(SCHEMA)
            await seed(pool)
            return pool
        except (OSError, asyncpg.PostgresError):
            await __import__("asyncio").sleep(1)
    raise RuntimeError("Could not connect to PostgreSQL")


async def seed(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM customer_accounts")
        companies = [
            ("Northwind Health", "Enterprise", "Scale", "Avery Chen"),
            ("Pinecone Labs", "Mid-market", "Growth", "Maya Patel"),
            ("Orbital Systems", "Enterprise", "Scale", "Jordan Lee"),
            ("Brightline Studio", "SMB", "Starter", "Sam Rivera"),
            ("Harbor & Co", "Mid-market", "Growth", "Taylor Brooks"),
        ]
        for index in range(count, 3000):
            base = companies[index % len(companies)]
            risk = (index * 17) % 100
            risk_score = round(risk / 100, 4)
            health = round(max(0.30, 0.94 - risk / 120), 2)
            account = await conn.fetchrow(
                """INSERT INTO customer_accounts (external_id, name, segment, plan, owner, health_score, risk_score)
                   VALUES ($1,$2,$3,$4,$5,$6,$7) ON CONFLICT (external_id) DO UPDATE SET risk_score=EXCLUDED.risk_score RETURNING id""",
                f"acct_{index + 1:04d}", f"{base[0]} {index // len(companies) + 1}", base[1], base[2], base[3], health, risk_score,
            )
            usage_change = round(-0.08 - (risk / 160), 2) if risk >= 45 else round(0.12 - risk / 300, 2)
            await conn.execute(
                "INSERT INTO customer_activity (account_id, period_start, active_users, sessions, usage_change) VALUES ($1,$2,$3,$4,$5)",
                account["id"], date.today() - timedelta(days=30), max(4, 42 - risk // 2), max(20, 240 - risk * 2), usage_change,
            )
            await conn.execute("INSERT INTO subscriptions (account_id,plan,monthly_revenue,contract_start,contract_end,renewal_date,status) VALUES ($1,$2,$3,$4,$5,$6,$7)", account["id"], base[2], 1800 + (index % 8) * 750, date.today() - timedelta(days=300), date.today() + timedelta(days=65 + (index * 11) % 160), date.today() + timedelta(days=21 + (index * 11) % 160), "active")
            await conn.execute(
                "INSERT INTO contracts (account_id, renewal_date, annual_value) VALUES ($1,$2,$3)",
                account["id"], date.today() + timedelta(days=21 + (index * 11) % 160), 18000 + (index % 8) * 7500,
            )
            await conn.execute("INSERT INTO product_usage (account_id,usage_date,active_users,sessions,features_used,api_calls,projects_created) VALUES ($1,$2,$3,$4,$5,$6,$7)", account["id"], date.today() - timedelta(days=7), max(4, 42 - risk // 2), max(20, 240 - risk * 2), max(2, 12 - risk // 10), max(40, 900 - risk * 7), max(1, 24 - risk // 5))
            await conn.execute("INSERT INTO support_tickets (account_id,category,priority,status,resolution_hours,csat_score) VALUES ($1,$2,$3,$4,$5,$6)", account["id"], "Reporting" if risk >= 45 else "How-to", "high" if risk >= 70 else "normal", "open" if risk >= 45 else "resolved", 72 if risk >= 45 else 12, 2.8 if risk >= 70 else 4.4)
            await conn.execute("INSERT INTO payments (account_id,invoice_date,amount,payment_date,payment_status,days_overdue) VALUES ($1,$2,$3,$4,$5,$6)", account["id"], date.today() - timedelta(days=21), 1800 + (index % 8) * 750, None if risk >= 80 else date.today() - timedelta(days=4), "overdue" if risk >= 80 else "paid", 21 if risk >= 80 else 0)
            await conn.execute("INSERT INTO nps_surveys (account_id,survey_date,score,feedback) VALUES ($1,$2,$3,$4)", account["id"], date.today() - timedelta(days=12), max(1, 9 - risk // 14), "The reporting workflow needs attention." if risk >= 60 else "The team is happy with the product.")
            await conn.execute("INSERT INTO customer_documents (account_id,source_type,source_name,content,embedding) VALUES ($1,$2,$3,$4,$5)", account["id"], "account_note", f"note_{index + 1:04d}.txt", "Customer feedback indicates reporting friction and a review of alternatives." if risk >= 60 else "Customer is using the core workflow successfully.", "[0.8,0.2,0.1]" if risk >= 60 else "[0.1,0.8,0.2]")
            await conn.execute("INSERT INTO customer_outcomes (account_id,outcome,outcome_date,reason) VALUES ($1,$2,$3,$4)", account["id"], "CHURNED" if risk >= 85 else "RENEWED", date.today() - timedelta(days=30), "pricing" if risk >= 85 else None)
            if risk >= 45:
                await conn.execute(
                    "INSERT INTO support_threads (account_id, subject, content, sentiment, resolved) VALUES ($1,$2,$3,$4,$5)",
                    account["id"], "Workflow friction reported", "Repeated export failures and slow resolution are blocking the team's weekly process.", -0.62, False,
                )


async def save_run(pool: asyncpg.Pool | None, run: Any) -> None:
    if not pool:
        return
    state = {
        "nodes": run.nodes,
        "plan": run.plan.model_dump() if run.plan else None,
        "tasks": [task.model_dump() for task in run.tasks],
        "claims": [claim.model_dump() for claim in run.claims],
    }
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO runs (id, objective, status, approval_mode, progress, current_node, state, report, error, updated_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,NOW())
               ON CONFLICT (id) DO UPDATE SET status=$3, progress=$5, current_node=$6, state=$7, report=$8, error=$9, updated_at=NOW()""",
            run.id, run.objective, run.status, run.approval_mode, run.progress, run.current_node,
            json.dumps(state), json.dumps(run.report) if run.report else None, run.error,
        )


async def add_event(pool: asyncpg.Pool | None, run_id: str, event: dict[str, Any]) -> None:
    if not pool:
        return
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO run_events (id, run_id, kind, message, agent, metadata, created_at) VALUES ($1,$2,$3,$4,$5,$6,NOW()) ON CONFLICT DO NOTHING",
            event["id"], run_id, event["kind"], event["message"], event["agent"], json.dumps(event["metadata"]),
        )


async def save_evidence(pool: asyncpg.Pool | None, run_id: str, evidence: list[dict[str, Any]]) -> None:
    if not pool:
        return
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM run_evidence WHERE run_id=$1", run_id)
        for item in evidence:
            await conn.execute("INSERT INTO run_evidence (run_id,title,source,confidence,excerpt,tag) VALUES ($1,$2,$3,$4,$5,$6)", run_id, item["title"], item["source"], item["confidence"], item["excerpt"], item["tag"])


async def load_run(pool: asyncpg.Pool | None, run_id: str) -> dict[str, Any] | None:
    if not pool:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM runs WHERE id=$1", run_id)
        if not row:
            return None
        events = await conn.fetch("SELECT id,kind,message,agent,metadata,created_at FROM run_events WHERE run_id=$1 ORDER BY created_at", run_id)
        evidence = await conn.fetch("SELECT title,source,confidence,excerpt,tag FROM run_evidence WHERE run_id=$1 ORDER BY id", run_id)
        def decode(value: Any) -> Any:
            return json.loads(value) if isinstance(value, str) else value
        state = decode(row["state"]) or {}
        return {
            "id": row["id"], "objective": row["objective"], "status": row["status"], "approval_mode": row["approval_mode"],
            "progress": row["progress"], "current_node": row["current_node"], "report": decode(row["report"]), "error": row["error"],
            "created_at": row["created_at"].isoformat(), "updated_at": row["updated_at"].isoformat(),
            "nodes": state.get("nodes", []), "plan": state.get("plan"), "tasks": state.get("tasks", []), "claims": state.get("claims", []),
            "events": [{"id": event["id"], "at": event["created_at"].isoformat(), "kind": event["kind"], "message": event["message"], "agent": event["agent"], "metadata": decode(event["metadata"]) or {}} for event in events],
            "evidence": [dict(item) for item in evidence],
        }


async def account_snapshot(pool: asyncpg.Pool | None) -> dict[str, int]:
    if not pool:
        return {"accounts": 1248, "high_risk": 17, "evidence_chunks": 86}
    async with pool.acquire() as conn:
        accounts = await conn.fetchval("SELECT COUNT(*) FROM customer_accounts")
        high_risk = await conn.fetchval("SELECT COUNT(*) FROM customer_accounts WHERE risk_score >= 0.70")
        chunks = await conn.fetchval("SELECT COUNT(*) FROM customer_documents")
        return {"accounts": accounts, "high_risk": high_risk, "evidence_chunks": chunks}


async def list_runs(pool: asyncpg.Pool | None, limit: int = 40) -> list[dict[str, Any]]:
    if not pool:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, objective, status, progress, current_node, approval_mode, created_at, updated_at FROM runs ORDER BY created_at DESC LIMIT $1", limit)
        return [{"id": row["id"], "objective": row["objective"], "status": row["status"], "progress": row["progress"], "current_node": row["current_node"], "approval_mode": row["approval_mode"], "created_at": row["created_at"].isoformat(), "updated_at": row["updated_at"].isoformat()} for row in rows]
