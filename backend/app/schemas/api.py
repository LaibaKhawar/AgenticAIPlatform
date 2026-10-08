"""HTTP request/response schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import get_settings
from app.models.enums import (
    AccountTier,
    ActionType,
    ApprovalStatus,
    ClaimStatus,
    ClaimType,
    RiskLevel,
    RunStatus,
    TaskStatus,
    WorkflowMode,
    WorkflowType,
)

T = TypeVar("T")


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class Page(ApiModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total


class PaginationParams(BaseModel):
    limit: Annotated[int, Field(ge=1, le=500)] = 25
    offset: Annotated[int, Field(ge=0, le=1_000_000)] = 0

    @field_validator("limit")
    @classmethod
    def _cap(cls, value: int) -> int:
        return min(value, get_settings().api_max_page_size)


# --------------------------------------------------------------------------- #
# Health / system
# --------------------------------------------------------------------------- #


class HealthResponse(ApiModel):
    status: str
    product: str
    version: str
    environment: str
    database: str
    pgvector: bool
    redis: str
    llm_provider: str
    llm_model: str
    embedding_provider: str
    failure_injection: bool
    checks: dict[str, Any] = Field(default_factory=dict)


class SystemInfoResponse(ApiModel):
    product: str
    tagline: str
    environment: str
    workflow_executor: str
    llm_provider: str
    llm_model: str
    embedding_provider: str
    embedding_model: str
    tracing_enabled: bool
    langfuse_configured: bool
    failure_injection: dict[str, Any]
    limits: dict[str, Any]
    agents: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    risk_model: dict[str, Any]
    approval_policy: list[dict[str, Any]]


# --------------------------------------------------------------------------- #
# Customers
# --------------------------------------------------------------------------- #


class SubscriptionSummary(ApiModel):
    plan: str
    monthly_recurring_revenue: float
    annual_contract_value: float
    contract_start: date
    contract_end: date
    renewal_date: date
    subscription_status: str
    seats_purchased: int
    days_to_renewal: int | None = None


class CustomerListItem(ApiModel):
    id: uuid.UUID
    external_id: str
    company_name: str
    industry: str
    country: str
    account_tier: str
    account_manager: str
    employee_count: int
    subscription: SubscriptionSummary | None = None
    outcome: str | None = None


class UsagePoint(ApiModel):
    usage_date: date
    active_users: int
    sessions: int
    total_logins: int
    api_calls: int
    projects_created: int
    feature_adoption_score: float
    seats_active: int


class TicketSummary(ApiModel):
    id: uuid.UUID
    external_ticket_id: str
    created_at: datetime
    resolved_at: datetime | None
    category: str
    priority: str
    status: str
    resolution_hours: float | None
    csat_score: float | None
    subject: str


class PaymentSummaryItem(ApiModel):
    id: uuid.UUID
    invoice_date: date
    due_date: date | None
    amount: float
    payment_date: date | None
    payment_status: str
    days_overdue: int


class NpsResponseItem(ApiModel):
    id: uuid.UUID
    response_date: date
    score: int
    feedback: str


class DocumentListItem(ApiModel):
    id: uuid.UUID
    source_type: str
    title: str
    source_date: date
    chars: int
    chunk_count: int = 0


class DocumentDetail(ApiModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    source_type: str
    title: str
    source_date: date
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class RiskSignalItem(ApiModel):
    key: str
    label: str
    value: float | None
    unit: str
    severity: float
    weight: float
    contribution: float
    detail: str


class CustomerRiskResponse(ApiModel):
    customer_id: uuid.UUID
    external_id: str
    company_name: str
    heuristic_risk_score: float
    risk_level: RiskLevel
    coverage: float
    days_to_renewal: int | None
    renewal_multiplier: float
    missing_signals: list[str]
    signals: list[RiskSignalItem]
    model: dict[str, Any]


class InvestigationHistoryItem(ApiModel):
    id: uuid.UUID
    run_id: uuid.UUID
    risk_score: float
    risk_level: str
    confidence: float
    summary: str
    created_at: datetime


class CustomerDetailResponse(ApiModel):
    customer: CustomerListItem
    usage: list[UsagePoint]
    usage_summary: dict[str, Any]
    tickets: list[TicketSummary]
    support_summary: dict[str, Any]
    payments: list[PaymentSummaryItem]
    payment_summary: dict[str, Any]
    nps: list[NpsResponseItem]
    nps_summary: dict[str, Any]
    documents: list[DocumentListItem]
    risk: CustomerRiskResponse
    outcome: dict[str, Any] | None = None
    investigations: list[InvestigationHistoryItem] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Runs
# --------------------------------------------------------------------------- #


class CreateRunRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    objective: str = Field(min_length=20, max_length=4000)
    account_tier: AccountTier | None = None
    renewal_window_days: Annotated[int, Field(ge=1, le=400)] | None = None
    max_accounts: Annotated[int, Field(ge=1, le=50)] | None = None
    workflow_mode: WorkflowMode = WorkflowMode.STANDARD
    risk_threshold: Annotated[float, Field(ge=0, le=100)] | None = None
    workflow_type: WorkflowType = WorkflowType.CHURN_INVESTIGATION
    created_by: str = Field(default="operator", max_length=120)

    def parameters(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "account_tier": self.account_tier.value if self.account_tier else None,
                "renewal_window_days": self.renewal_window_days,
                "max_accounts": self.max_accounts,
                "workflow_mode": self.workflow_mode.value,
                "risk_threshold": self.risk_threshold,
            }.items()
            if value is not None
        }


class CreateRunResponse(ApiModel):
    run_id: uuid.UUID
    status: RunStatus
    objective: str
    created_at: datetime
    workflow_type: str
    parameters: dict[str, Any]
    executor: str


class RunListItem(ApiModel):
    id: uuid.UUID
    objective: str
    workflow_type: str
    workflow_mode: str
    status: RunStatus
    progress: int
    current_stage: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
    error_message: str | None
    created_by: str
    duration_seconds: float | None = None
    investigation_count: int = 0
    pending_approvals: int = 0


class RunTaskItem(ApiModel):
    id: uuid.UUID
    task_key: str
    agent_type: str
    description: str
    stage: str
    status: TaskStatus
    dependencies: list[str]
    retry_count: int
    max_retries: int
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    output_summary: dict[str, Any] = Field(default_factory=dict)


class AuditEventItem(ApiModel):
    id: uuid.UUID
    event_type: str
    actor_type: str
    actor_id: str
    message: str
    payload: dict[str, Any]
    customer_id: uuid.UUID | None
    trace_id: str | None
    created_at: datetime


class EvidenceItemResponse(ApiModel):
    id: uuid.UUID
    reference: str
    customer_id: uuid.UUID | None
    source_type: str
    source_id: str
    title: str
    content: str
    source_date: date | None
    relevance_score: float | None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ClaimItemResponse(ApiModel):
    id: uuid.UUID
    claim_key: str
    customer_id: uuid.UUID | None
    claim_text: str
    final_text: str | None
    claim_type: ClaimType
    status: ClaimStatus
    confidence: float
    verification_reason: str | None
    suggested_revision: str | None
    evidence_references: list[str] = Field(default_factory=list)
    verified_at: datetime | None
    created_at: datetime


class RecommendedActionResponse(ApiModel):
    action_type: ActionType
    description: str
    rationale: str = ""
    priority: int = 3
    requires_approval: bool = False
    approval_status: str | None = None


class InvestigationResponse(ApiModel):
    id: uuid.UUID
    run_id: uuid.UUID
    customer_id: uuid.UUID
    external_id: str = ""
    company_name: str = ""
    account_tier: str = ""
    renewal_date: date | None = None
    monthly_recurring_revenue: float | None = None
    risk_score: float
    heuristic_risk_score: float
    risk_level: RiskLevel
    confidence: float
    summary: str
    risk_factors: list[dict[str, Any]]
    quantitative_signals: dict[str, Any]
    recommended_actions: list[RecommendedActionResponse]
    data_gaps: list[str]
    claims: list[ClaimItemResponse] = Field(default_factory=list)
    evidence: list[EvidenceItemResponse] = Field(default_factory=list)
    created_at: datetime


class RunDetailResponse(ApiModel):
    run: RunListItem
    parameters: dict[str, Any]
    plan: dict[str, Any] | None
    stages: list[dict[str, Any]]
    tasks: list[RunTaskItem]
    events: list[AuditEventItem]
    verification: dict[str, Any] | None = None
    llm_usage: dict[str, Any] | None = None
    investigation_summaries: list[dict[str, Any]] = Field(default_factory=list)
    approvals: list[ApprovalResponse] = Field(default_factory=list)
    has_report: bool = False


class ReportResponse(ApiModel):
    id: uuid.UUID
    run_id: uuid.UUID
    title: str
    executive_summary: str
    report_payload: dict[str, Any]
    markdown_content: str
    created_at: datetime


class ReportListItem(ApiModel):
    id: uuid.UUID
    run_id: uuid.UUID
    title: str
    executive_summary: str
    created_at: datetime
    account_count: int = 0
    objective: str = ""


# --------------------------------------------------------------------------- #
# Approvals
# --------------------------------------------------------------------------- #


class ApprovalResponse(ApiModel):
    id: uuid.UUID
    run_id: uuid.UUID
    customer_id: uuid.UUID | None
    company_name: str = ""
    action_type: ActionType
    proposed_action: str
    action_payload: dict[str, Any]
    status: ApprovalStatus
    reason: str
    requested_at: datetime
    reviewed_at: datetime | None
    reviewed_by: str | None
    reviewer_comment: str | None
    run_objective: str = ""


class ApprovalDecisionRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    reviewed_by: str = Field(default="operator", max_length=120)
    comment: str | None = Field(default=None, max_length=2000)


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #


class DashboardResponse(ApiModel):
    investigations_completed: int
    runs_running: int
    runs_failed: int
    runs_total: int
    pending_approvals: int
    high_risk_customers: int
    avg_run_duration_seconds: float | None
    verified_claim_pct: float | None
    unsupported_claim_pct: float | None
    partially_supported_claim_pct: float | None
    total_customers: int
    renewing_within_90_days: int
    evidence_records: int
    embedded_chunks: int
    llm_usage: dict[str, Any]
    recent_runs: list[RunListItem]
    high_risk_accounts: list[dict[str, Any]]
    dataset: dict[str, Any]


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #


class EvaluationRequest(BaseModel):
    name: str = Field(default="synthetic-churn-evaluation", max_length=200)
    sample_size: Annotated[int, Field(ge=10, le=5000)] = 600
    retrieval_sample: Annotated[int, Field(ge=1, le=200)] = 25
    include_workflow_metrics: bool = True
    run_async: bool = False


class EvaluationResponse(ApiModel):
    id: uuid.UUID
    name: str
    status: str
    dataset_description: str
    parameters: dict[str, Any]
    metrics: dict[str, Any]
    details: dict[str, Any]
    error_message: str | None
    duration_ms: int | None
    created_at: datetime


class ErrorResponse(BaseModel):
    error: dict[str, Any]


RunDetailResponse.model_rebuild()
