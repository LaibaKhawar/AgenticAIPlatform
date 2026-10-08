"""Customer domain tables (the "business" side of the warehouse)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import get_settings
from app.db.base import Base, TimestampMixin, new_uuid
from app.models.enums import (
    AccountTier,
    CustomerOutcome,
    DocumentSourceType,
    PaymentStatus,
    SubscriptionStatus,
    TicketPriority,
    TicketStatus,
)

EMBEDDING_DIM = get_settings().embedding_dim


def _enum_check(column: str, enum_cls: type[StrEnum], name: str) -> CheckConstraint:
    values = ", ".join(f"'{member.value}'" for member in enum_cls)
    return CheckConstraint(f"{column} IN ({values})", name=name)


class Customer(Base, TimestampMixin):
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    company_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    industry: Mapped[str] = mapped_column(String(80), nullable=False)
    country: Mapped[str] = mapped_column(String(80), nullable=False)
    company_size: Mapped[str] = mapped_column(String(40), nullable=False)
    employee_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    account_tier: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    account_manager: Mapped[str] = mapped_column(String(120), nullable=False)
    # Persona label used by the synthetic generator and the evaluation harness.
    # Never shown to agents as a feature — it would leak the answer.
    scenario_persona: Mapped[str | None] = mapped_column(String(60), nullable=True)

    subscription: Mapped[Subscription | None] = relationship(
        back_populates="customer", uselist=False, cascade="all, delete-orphan"
    )
    usage: Mapped[list[ProductUsage]] = relationship(
        back_populates="customer", cascade="all, delete-orphan", passive_deletes=True
    )
    tickets: Mapped[list[SupportTicket]] = relationship(
        back_populates="customer", cascade="all, delete-orphan", passive_deletes=True
    )
    payments: Mapped[list[Payment]] = relationship(
        back_populates="customer", cascade="all, delete-orphan", passive_deletes=True
    )
    nps_surveys: Mapped[list[NpsSurvey]] = relationship(
        back_populates="customer", cascade="all, delete-orphan", passive_deletes=True
    )
    documents: Mapped[list[CustomerDocument]] = relationship(
        back_populates="customer", cascade="all, delete-orphan", passive_deletes=True
    )
    outcome: Mapped[CustomerOutcomeRecord | None] = relationship(
        back_populates="customer", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (
        _enum_check("account_tier", AccountTier, "account_tier_valid"),
        CheckConstraint("employee_count >= 0", name="employee_count_non_negative"),
        Index("ix_customers_tier_name", "account_tier", "company_name"),
    )


class Subscription(Base, TimestampMixin):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    plan: Mapped[str] = mapped_column(String(60), nullable=False)
    monthly_recurring_revenue: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    annual_contract_value: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    contract_start: Mapped[date] = mapped_column(Date, nullable=False)
    contract_end: Mapped[date] = mapped_column(Date, nullable=False)
    renewal_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    subscription_status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    seats_purchased: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    customer: Mapped[Customer] = relationship(back_populates="subscription")

    __table_args__ = (
        _enum_check("subscription_status", SubscriptionStatus, "subscription_status_valid"),
        CheckConstraint("monthly_recurring_revenue >= 0", name="mrr_non_negative"),
        CheckConstraint("seats_purchased >= 0", name="seats_non_negative"),
        CheckConstraint("contract_end >= contract_start", name="contract_dates_ordered"),
        Index("ix_subscriptions_renewal_status", "renewal_date", "subscription_status"),
    )


class ProductUsage(Base):
    __tablename__ = "product_usage"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    usage_date: Mapped[date] = mapped_column(Date, nullable=False)
    active_users: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_logins: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sessions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    projects_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    api_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    feature_adoption_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    seats_active: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    customer: Mapped[Customer] = relationship(back_populates="usage")

    __table_args__ = (
        UniqueConstraint("customer_id", "usage_date", name="uq_product_usage_customer_date"),
        Index("ix_product_usage_customer_date", "customer_id", "usage_date"),
        CheckConstraint("active_users >= 0", name="active_users_non_negative"),
    )


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    external_ticket_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    category: Mapped[str] = mapped_column(String(60), nullable=False)
    priority: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    resolution_hours: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    csat_score: Mapped[float | None] = mapped_column(Numeric(3, 1), nullable=True)
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    customer: Mapped[Customer] = relationship(back_populates="tickets")

    __table_args__ = (
        _enum_check("priority", TicketPriority, "ticket_priority_valid"),
        _enum_check("status", TicketStatus, "ticket_status_valid"),
        CheckConstraint("csat_score IS NULL OR (csat_score >= 1 AND csat_score <= 5)", name="csat_range"),
        Index("ix_support_tickets_customer_created", "customer_id", "created_at"),
    )


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Nullable on purpose: real billing exports contain invoices with no due date.
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    payment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    payment_status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    days_overdue: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    customer: Mapped[Customer] = relationship(back_populates="payments")

    __table_args__ = (
        _enum_check("payment_status", PaymentStatus, "payment_status_valid"),
        CheckConstraint("amount >= 0", name="payment_amount_non_negative"),
        CheckConstraint("days_overdue >= 0", name="days_overdue_non_negative"),
        Index("ix_payments_customer_invoice", "customer_id", "invoice_date"),
    )


class NpsSurvey(Base):
    __tablename__ = "nps_surveys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    response_date: Mapped[date] = mapped_column(Date, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    feedback: Mapped[str] = mapped_column(Text, nullable=False, default="")

    customer: Mapped[Customer] = relationship(back_populates="nps_surveys")

    __table_args__ = (
        CheckConstraint("score >= 0 AND score <= 10", name="nps_score_range"),
        Index("ix_nps_surveys_customer_date", "customer_id", "response_date"),
    )


class CustomerDocument(Base):
    __tablename__ = "customer_documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    source_date: Mapped[date] = mapped_column(Date, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    doc_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    customer: Mapped[Customer] = relationship(back_populates="documents")
    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        _enum_check("source_type", DocumentSourceType, "document_source_type_valid"),
        Index("ix_customer_documents_customer_date", "customer_id", "source_date"),
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer_documents.id", ondelete="CASCADE"), nullable=False
    )
    # Denormalised so vector search can filter by customer without a join.
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    document: Mapped[CustomerDocument] = relationship(back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_document_chunks_doc_index"),
        Index("ix_document_chunks_customer", "customer_id"),
    )


class CustomerOutcomeRecord(Base):
    __tablename__ = "customer_outcomes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    outcome: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    outcome_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    churn_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    customer: Mapped[Customer] = relationship(back_populates="outcome")

    __table_args__ = (_enum_check("outcome", CustomerOutcome, "customer_outcome_valid"),)
