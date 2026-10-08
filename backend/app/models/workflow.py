"""Workflow, evidence and audit tables (the "execution" side)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, new_uuid
from app.models.enums import (
    ActionType,
    ActorType,
    ApprovalStatus,
    ClaimStatus,
    ClaimType,
    EvaluationStatus,
    EvidenceSourceType,
    RiskLevel,
    RunStatus,
    TaskStatus,
)


def _enum_check(column: str, enum_cls: type[StrEnum], name: str) -> CheckConstraint:
    values = ", ".join(f"'{member.value}'" for member in enum_cls)
    return CheckConstraint(f"{column} IN ({values})", name=name)


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    workflow_type: Mapped[str] = mapped_column(String(60), nullable=False)
    workflow_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="STANDARD")
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_stage: Mapped[str] = mapped_column(String(60), nullable=False, default="objective_received")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False, default="operator")
    # Operator parameters, plan snapshot, token/cost counters, cancellation marker.
    run_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    tasks: Mapped[list[RunTask]] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )
    evidence: Mapped[list[Evidence]] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )
    claims: Mapped[list[Claim]] = relationship(back_populates="run", cascade="all, delete-orphan", passive_deletes=True)
    investigations: Mapped[list[Investigation]] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )
    report: Mapped[Report | None] = relationship(back_populates="run", uselist=False, cascade="all, delete-orphan")
    approvals: Mapped[list[Approval]] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        _enum_check("status", RunStatus, "run_status_valid"),
        CheckConstraint("progress >= 0 AND progress <= 100", name="run_progress_range"),
        Index("ix_runs_status_created", "status", "created_at"),
    )


class RunTask(Base):
    __tablename__ = "run_tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    task_key: Mapped[str] = mapped_column(String(120), nullable=False)
    agent_type: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    stage: Mapped[str] = mapped_column(String(60), nullable=False, default="execution")
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    dependencies: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    output_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Guards against duplicate Celery deliveries claiming the same task twice.
    dispatch_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    run: Mapped[Run] = relationship(back_populates="tasks")

    __table_args__ = (
        UniqueConstraint("run_id", "task_key", name="uq_run_tasks_run_key"),
        _enum_check("status", TaskStatus, "task_status_valid"),
        CheckConstraint("retry_count >= 0", name="task_retry_non_negative"),
        Index("ix_run_tasks_run_status", "run_id", "status"),
    )


claim_evidence = Table(
    "claim_evidence",
    Base.metadata,
    Column("claim_id", UUID(as_uuid=True), ForeignKey("claims.id", ondelete="CASCADE"), primary_key=True),
    Column("evidence_id", UUID(as_uuid=True), ForeignKey("evidence.id", ondelete="CASCADE"), primary_key=True),
    Index("ix_claim_evidence_evidence", "evidence_id"),
)


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True
    )
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    # Stable identifier of the underlying row (document chunk id, ticket id, ...).
    source_id: Mapped[str] = mapped_column(String(120), nullable=False)
    # Short human-readable handle the agents cite, e.g. "EV-3".
    reference: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    relevance_score: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    evidence_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    run: Mapped[Run] = relationship(back_populates="evidence")
    claims: Mapped[list[Claim]] = relationship(secondary=claim_evidence, back_populates="evidence_items")

    __table_args__ = (
        _enum_check("source_type", EvidenceSourceType, "evidence_source_type_valid"),
        # Idempotency: re-running a retrieval for the same run/customer/source
        # updates instead of duplicating.
        UniqueConstraint("run_id", "customer_id", "source_id", name="uq_evidence_run_customer_source"),
        # Scoped to the customer, matching how references are allocated — see
        # EvidenceRepository.next_reference_index.
        UniqueConstraint(
            "run_id", "customer_id", "reference", name="uq_evidence_run_customer_reference"
        ),
        Index("ix_evidence_run_customer", "run_id", "customer_id"),
    )


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True
    )
    claim_key: Mapped[str] = mapped_column(String(120), nullable=False)
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    claim_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, default=0)
    verification_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_revision: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Set when the verifier rewrote a partially supported claim into something
    # the report can safely state.
    final_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    run: Mapped[Run] = relationship(back_populates="claims")
    evidence_items: Mapped[list[Evidence]] = relationship(secondary=claim_evidence, back_populates="claims")

    __table_args__ = (
        UniqueConstraint("run_id", "claim_key", name="uq_claims_run_key"),
        _enum_check("claim_type", ClaimType, "claim_type_valid"),
        _enum_check("status", ClaimStatus, "claim_status_valid"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="claim_confidence_range"),
        Index("ix_claims_run_customer", "run_id", "customer_id"),
    )


class Investigation(Base):
    __tablename__ = "investigations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    risk_score: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    heuristic_risk_score: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, default=0)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    risk_factors: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    quantitative_signals: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    recommended_actions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    data_gaps: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    run: Mapped[Run] = relationship(back_populates="investigations")

    __table_args__ = (
        UniqueConstraint("run_id", "customer_id", name="uq_investigations_run_customer"),
        _enum_check("risk_level", RiskLevel, "investigation_risk_level_valid"),
        CheckConstraint("risk_score >= 0 AND risk_score <= 100", name="investigation_risk_range"),
    )


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    executive_summary: Mapped[str] = mapped_column(Text, nullable=False)
    report_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    markdown_content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    run: Mapped[Run] = relationship(back_populates="report")


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True
    )
    action_type: Mapped[str] = mapped_column(String(40), nullable=False)
    proposed_action: Mapped[str] = mapped_column(Text, nullable=False)
    action_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Deterministic dedupe key: one approval per (run, customer, action).
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reviewer_comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped[Run] = relationship(back_populates="approvals")

    __table_args__ = (
        UniqueConstraint("run_id", "idempotency_key", name="uq_approvals_run_idempotency"),
        _enum_check("action_type", ActionType, "approval_action_type_valid"),
        _enum_check("status", ApprovalStatus, "approval_status_valid"),
        Index("ix_approvals_status_requested", "status", "requested_at"),
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), nullable=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("run_tasks.id", ondelete="SET NULL"), nullable=True
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(120), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    __table_args__ = (
        _enum_check("actor_type", ActorType, "audit_actor_type_valid"),
        Index("ix_audit_events_run_created", "run_id", "created_at"),
    )


class LlmCall(Base):
    """Per-call LLM telemetry: latency, tokens, cost, retries, validity."""

    __tablename__ = "llm_calls"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), nullable=True
    )
    task_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    agent: Mapped[str] = mapped_column(String(40), nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    operation: Mapped[str] = mapped_column(String(60), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False, default=0)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    valid_output: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    __table_args__ = (Index("ix_llm_calls_run_agent", "run_id", "agent"),)


class EvaluationRun(Base, TimestampMixin):
    __tablename__ = "evaluation_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    dataset_description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (_enum_check("status", EvaluationStatus, "evaluation_status_valid"),)
