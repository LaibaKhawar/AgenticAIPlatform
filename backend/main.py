from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class RunRequest(BaseModel):
    objective: str = Field(min_length=12, max_length=4000)
    approval_mode: Literal["required", "autonomous"] = "required"


class Task(BaseModel):
    id: str
    agent: str
    description: str
    dependencies: list[str] = Field(default_factory=list)
    status: str = "queued"
    retry_count: int = 0


class ExecutionPlan(BaseModel):
    objective: str
    tasks: list[Task]


class Claim(BaseModel):
    id: str
    claim: str
    verification_status: str = "pending"
    confidence: float = 0
    evidence_ids: list[str] = Field(default_factory=list)
    reason: str = ""


class RunState(BaseModel):
    id: str
    objective: str
    status: str = "queued"
    created_at: str = Field(default_factory=now)
    updated_at: str = Field(default_factory=now)
    progress: int = 0
    current_node: str = "planner"
    approval_mode: str = "required"
    plan: ExecutionPlan | None = None
    tasks: list[Task] = Field(default_factory=list)
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    report: dict[str, Any] | None = None
    error: str | None = None


class ApprovalRequest(BaseModel):
    approved: bool
    note: str = ""


runs: dict[str, RunState] = {}
approval_events: dict[str, asyncio.Event] = {}
db_pool = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global db_pool
    db_pool = await db.connect()
    yield
    if db_pool:
        await db_pool.close()

app = FastAPI(title="Cogniflow Agent Platform", version="0.1.0", lifespan=lifespan)


def add_event(run: RunState, kind: str, message: str, agent: str, metadata: dict[str, Any] | None = None) -> None:
    event = {"id": str(uuid.uuid4()), "at": now(), "kind": kind, "message": message, "agent": agent, "metadata": metadata or {}}
    run.events.append(event)
    run.updated_at = now()
    if db_pool:
        asyncio.create_task(db.add_event(db_pool, run.id, event))


def set_node(run: RunState, node_id: str, status: str, label: str, detail: str = "") -> None:
    existing = next((node for node in run.nodes if node["id"] == node_id), None)
    if existing:
        existing.update({"status": status, "detail": detail})
    else:
        run.nodes.append({"id": node_id, "label": label, "status": status, "detail": detail})


def build_plan(objective: str) -> ExecutionPlan:
    tasks = [
        Task(id="T1", agent="sql_agent", description="Identify customers with upcoming renewals and behavioral risk signals."),
        Task(id="T2", agent="risk_agent", description="Calculate explainable churn indicators from usage, support, payment, and NPS data.", dependencies=["T1"]),
        Task(id="T3", agent="research_agent", description="Retrieve qualitative customer evidence from documents and support threads.", dependencies=["T2"]),
        Task(id="T4", agent="investigator_agent", description="Investigate the highest-risk accounts in parallel and propose interventions.", dependencies=["T2", "T3"]),
        Task(id="T5", agent="verifier_agent", description="Validate every report claim against retrieved evidence IDs.", dependencies=["T4"]),
        Task(id="T6", agent="report_agent", description="Generate a structured evidence-backed report and approval actions.", dependencies=["T5"]),
    ]
    return ExecutionPlan(objective=objective, tasks=tasks)


async def pause(run: RunState, seconds: float = 0.65) -> None:
    await asyncio.sleep(seconds)


async def workflow(run_id: str) -> None:
    run = runs[run_id]
    try:
        run.status = "running"
        run.current_node = "planner"
        run.plan = build_plan(run.objective)
        run.tasks = run.plan.tasks
        await db.save_run(db_pool, run)
        set_node(run, "planner", "running", "Planner", "Decomposing objective")
        add_event(run, "plan", "Objective received. Building a dependency-aware execution graph.", "planner", {"trace_id": run.id[:8], "task_count": len(run.tasks), "structured_output": True})
        await pause(run)
        run.tasks[0].status = "complete"
        set_node(run, "planner", "complete", "Planner", "6 tasks, 4 specialists, 1 verifier")
        run.progress = 18
        await db.save_run(db_pool, run)

        run.current_node = "postgres"
        set_node(run, "postgres", "running", "Account intelligence", "Querying customer health signals")
        snapshot = await db.account_snapshot(db_pool)
        add_event(run, "tool", "Queried customer accounts, usage, support volume, and renewal dates.", "postgres-agent", {"rows": snapshot["accounts"], "latency_ms": 412})
        await pause(run)
        set_node(run, "postgres", "complete", "Account intelligence", f"{snapshot['accounts']} accounts scanned")
        run.progress = 38
        await db.save_run(db_pool, run)

        run.current_node = "vector"
        set_node(run, "vector", "running", "Evidence retrieval", "Searching semantic customer context")
        add_event(run, "tool", "Retrieved support conversations and product feedback for high-risk accounts.", "vector-agent", {"chunks": snapshot["evidence_chunks"], "top_k": 20})
        await pause(run)
        set_node(run, "vector", "complete", "Evidence retrieval", f"{snapshot['evidence_chunks']} relevant evidence chunks")
        run.progress = 55
        await db.save_run(db_pool, run)

        run.current_node = "investigator"
        set_node(run, "investigator", "running", "Investigator", "Triaging risk signals and external context")
        add_event(run, "agent", f"Ranked {snapshot['high_risk']} accounts above the churn-risk threshold.", "investigator-agent", {"threshold": 0.70, "high_risk": snapshot["high_risk"]})
        await pause(run)
        set_node(run, "investigator", "complete", "Investigator", f"{snapshot['high_risk']} accounts prioritized")
        run.progress = 70
        run.current_node = "parallel_investigations"
        set_node(run, "parallel_investigations", "running", "Parallel investigations", "Fan-out across highest-risk accounts")
        candidates = min(snapshot["high_risk"], 8)
        async def investigate(account_number: int) -> dict[str, Any]:
            await asyncio.sleep(0.12)
            return {"account": f"acct_{account_number + 1:04d}", "status": "complete"}
        investigated = await asyncio.gather(*(investigate(index) for index in range(candidates)))
        run.tasks[3].status = "complete"
        set_node(run, "parallel_investigations", "complete", "Parallel investigations", f"{len(investigated)} accounts investigated concurrently")
        add_event(run, "parallel", f"Investigated {len(investigated)} highest-risk accounts concurrently.", "investigator-agent", {"fan_out": len(investigated), "execution": "asyncio.gather"})
        run.progress = 76
        await db.save_run(db_pool, run)

        if run.approval_mode == "required":
            run.status = "awaiting_approval"
            run.current_node = "approval"
            set_node(run, "approval", "waiting", "Human approval", "Ready to create outreach recommendations")
            add_event(run, "approval", "Approval required before producing customer-facing recommendations.", "policy-gate", {"scope": "sensitive_action"})
            await db.save_run(db_pool, run)
            approval_events[run_id] = asyncio.Event()
            await approval_events[run_id].wait()
            if run.status == "rejected":
                return
            set_node(run, "approval", "approved", "Human approval", "Approved by workspace operator")
            run.status = "running"

        run.current_node = "verifier"
        set_node(run, "verifier", "running", "Verifier", "Checking claims against source evidence")
        run.claims = [
            Claim(id="claim_usage", claim="High-risk accounts show material product usage decline.", verification_status="supported", confidence=0.97, evidence_ids=["usage_signal"], reason="Usage and session metrics declined in the latest period."),
            Claim(id="claim_support", claim="Unresolved support friction is contributing to churn risk.", verification_status="supported", confidence=0.91, evidence_ids=["support_signal"], reason="Open support threads contain repeated workflow friction."),
            Claim(id="claim_cancel", claim="Every high-risk account has decided to cancel.", verification_status="rejected", confidence=0.94, evidence_ids=[], reason="Evidence shows risk and evaluation of alternatives, not a confirmed cancellation decision."),
        ]
        run.tasks[4].status = "complete"
        add_event(run, "verify", "Cross-checking risk scores, citations, and unsupported claims.", "verifier-agent", {"claims_checked": len(run.claims), "supported": 2, "rejected": 1})
        await pause(run)
        set_node(run, "verifier", "complete", "Verifier", "31 claims checked · 0 unresolved")
        run.progress = 88
        await db.save_run(db_pool, run)

        run.current_node = "report"
        set_node(run, "report", "running", "Report composer", "Assembling evidence-backed report")
        run.tasks[5].status = "running"
        await pause(run)
        run.evidence = [
            {"title": "Usage drop in the last 30 days", "source": "PostgreSQL · customer_activity", "confidence": 0.97, "excerpt": "Account usage fell 46% compared with the prior period.", "tag": "signal"},
            {"title": "Unresolved support friction", "source": "Vector search · support_threads", "confidence": 0.91, "excerpt": "Three conversations mention repeated export failures and slow resolution.", "tag": "context"},
            {"title": "Renewal window opens in 21 days", "source": "PostgreSQL · contracts", "confidence": 0.99, "excerpt": "The renewal date is close enough to prioritize an intervention.", "tag": "timing"},
        ]
        run.report = {"headline": f"{snapshot['high_risk']} accounts need intervention before their next renewal cycle.", "summary": "The strongest shared pattern is declining product usage combined with unresolved workflow friction. Prioritize the top five accounts for a success-team review this week.", "risk_score": 0.89, "recommended_actions": ["Assign an owner to the top five accounts", "Schedule a workflow review with each account", "Re-check product usage seven days after outreach"]}
        await db.save_evidence(db_pool, run.id, run.evidence)
        set_node(run, "report", "complete", "Report composer", "Evidence-backed report ready")
        run.tasks[5].status = "complete"
        run.progress = 100
        run.current_node = "complete"
        run.status = "complete"
        add_event(run, "complete", "Report generated with citations and recommended next actions.", "report-agent", {"evidence_items": 3})
        await db.save_run(db_pool, run)
    except Exception as exc:
        run.status = "failed"
        run.error = str(exc)
        add_event(run, "error", "Workflow stopped and checkpoint saved for retry.", "system", {"error": str(exc)})
        await db.save_run(db_pool, run)


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "service": "cogniflow-orchestrator", "database": "connected" if db_pool else "demo-fallback", "active_runs": sum(r.status in {"running", "awaiting_approval"} for r in runs.values()), "agents": 5}


@app.get("/api/runs")
async def list_runs() -> list[dict[str, Any]]:
    saved = await db.list_runs(db_pool)
    if saved:
        return saved
    return [{"id": run.id, "objective": run.objective, "status": run.status, "progress": run.progress, "current_node": run.current_node, "approval_mode": run.approval_mode, "created_at": run.created_at, "updated_at": run.updated_at} for run in sorted(runs.values(), key=lambda item: item.created_at, reverse=True)]


@app.get("/api/agents")
async def list_agents() -> list[dict[str, Any]]:
    return [
        {"id": "planner", "name": "Planner", "role": "Turns objectives into dependency-aware execution plans.", "status": "ready", "accent": "lemon", "tools": ["Structured outputs", "Task DAG"]},
        {"id": "sql-agent", "name": "Data intelligence", "role": "Reads safe, parameterized customer and product metrics from PostgreSQL.", "status": "ready", "accent": "sea", "tools": ["PostgreSQL", "Churn signals"]},
        {"id": "research-agent", "name": "Evidence retrieval", "role": "Finds relevant qualitative context across customer documents and support threads.", "status": "ready", "accent": "blue", "tools": ["pgvector", "Semantic search"]},
        {"id": "investigator", "name": "Investigator", "role": "Connects signals into account-level explanations and actions.", "status": "ready", "accent": "lemon", "tools": ["Parallel fan-out", "Risk ranking"]},
        {"id": "verifier", "name": "Verifier", "role": "Checks claims against evidence and rejects unsupported conclusions.", "status": "ready", "accent": "sea", "tools": ["Claim checking", "Citations"]},
    ]


@app.get("/api/sources")
async def list_sources() -> list[dict[str, Any]]:
    snapshot = await db.account_snapshot(db_pool)
    return [
        {"id": "postgres", "name": "PostgreSQL warehouse", "type": "Structured data", "status": "connected" if db_pool else "demo", "detail": f"{snapshot['accounts']:,} customer accounts · usage · contracts", "icon": "▦"},
        {"id": "pgvector", "name": "Customer evidence index", "type": "Semantic search", "status": "connected" if db_pool else "demo", "detail": f"{snapshot['evidence_chunks']:,} documents ready for retrieval", "icon": "⌁"},
        {"id": "apis", "name": "External research APIs", "type": "Optional connector", "status": "available", "detail": "Connect product, billing, and market context APIs", "icon": "↗"},
        {"id": "neo4j", "name": "Relationship graph", "type": "Optional connector", "status": "not connected", "detail": "Map customer, product, and stakeholder relationships", "icon": "◌"},
    ]


@app.post("/api/runs", response_model=RunState, status_code=202)
async def create_run(payload: RunRequest) -> RunState:
    run = RunState(id=f"run_{uuid.uuid4().hex[:10]}", objective=payload.objective, approval_mode=payload.approval_mode)
    runs[run.id] = run
    await db.save_run(db_pool, run)
    asyncio.create_task(workflow(run.id))
    return run


@app.get("/api/runs/{run_id}", response_model=RunState)
async def get_run(run_id: str) -> RunState:
    if run_id not in runs:
        saved = await db.load_run(db_pool, run_id)
        if saved:
            runs[run_id] = RunState.model_validate(saved)
        else:
            raise HTTPException(404, "Run not found")
    return runs[run_id]


@app.post("/api/runs/{run_id}/approve", response_model=RunState)
async def approve_run(run_id: str, payload: ApprovalRequest) -> RunState:
    run = runs.get(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    if run.status != "awaiting_approval":
        raise HTTPException(409, "Run is not waiting for approval")
    if not payload.approved:
        run.status = "rejected"
        run.error = payload.note or "Action rejected by operator"
        add_event(run, "rejected", run.error, "policy-gate")
    else:
        add_event(run, "approved", payload.note or "Action approved by operator.", "policy-gate")
    approval_events[run_id].set()
    return run


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(Path(__file__).parent.parent / "frontend" / "index.html")


app.mount("/static", StaticFiles(directory=Path(__file__).parent.parent / "frontend"), name="static")
