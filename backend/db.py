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
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
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
        if count:
            return
        companies = [
            ("Northwind Health", "Enterprise", "Scale", "Avery Chen"),
            ("Pinecone Labs", "Mid-market", "Growth", "Maya Patel"),
            ("Orbital Systems", "Enterprise", "Scale", "Jordan Lee"),
            ("Brightline Studio", "SMB", "Starter", "Sam Rivera"),
            ("Harbor & Co", "Mid-market", "Growth", "Taylor Brooks"),
        ]
        for index in range(60):
            base = companies[index % len(companies)]
            risk = (index * 17) % 100
            health = round(max(0.38, 0.94 - risk / 180), 2)
            account = await conn.fetchrow(
                """INSERT INTO customer_accounts (external_id, name, segment, plan, owner, health_score)
                   VALUES ($1,$2,$3,$4,$5,$6) RETURNING id""",
                f"acct_{index + 1:04d}", f"{base[0]} {index // len(companies) + 1}", base[1], base[2], base[3], health,
            )
            usage_change = round(-0.08 - (risk / 160), 2) if risk >= 45 else round(0.12 - risk / 300, 2)
            await conn.execute(
                "INSERT INTO customer_activity (account_id, period_start, active_users, sessions, usage_change) VALUES ($1,$2,$3,$4,$5)",
                account["id"], date.today() - timedelta(days=30), max(4, 42 - risk // 2), max(20, 240 - risk * 2), usage_change,
            )
            await conn.execute(
                "INSERT INTO contracts (account_id, renewal_date, annual_value) VALUES ($1,$2,$3)",
                account["id"], date.today() + timedelta(days=21 + (index * 11) % 160), 18000 + (index % 8) * 7500,
            )
            if risk >= 45:
                await conn.execute(
                    "INSERT INTO support_threads (account_id, subject, content, sentiment, resolved) VALUES ($1,$2,$3,$4,$5)",
                    account["id"], "Workflow friction reported", "Repeated export failures and slow resolution are blocking the team's weekly process.", -0.62, False,
                )


async def save_run(pool: asyncpg.Pool | None, run: Any) -> None:
    if not pool:
        return
    state = {"nodes": run.nodes}
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


async def account_snapshot(pool: asyncpg.Pool | None) -> dict[str, int]:
    if not pool:
        return {"accounts": 1248, "high_risk": 17, "evidence_chunks": 86}
    async with pool.acquire() as conn:
        accounts = await conn.fetchval("SELECT COUNT(*) FROM customer_accounts")
        high_risk = await conn.fetchval("SELECT COUNT(*) FROM customer_accounts WHERE health_score < 0.70")
        chunks = await conn.fetchval("SELECT COUNT(*) FROM support_threads")
        return {"accounts": accounts, "high_risk": high_risk, "evidence_chunks": chunks}
