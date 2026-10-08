"""Read-only customer tools.

Each tool is a thin, validated wrapper over a repository method plus the
deterministic analytics layer. Inputs are Pydantic models with bounds, so an
agent cannot ask for 10,000 rows or a malformed identifier.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from app.analytics import metrics as M
from app.analytics.risk import assess_risk
from app.core.clock import today as clock_today
from app.core.errors import ResourceNotFoundError, ToolInputError
from app.models.enums import AccountTier, ToolAccess
from app.repositories.customers import CustomerRepository
from app.tools.registry import ToolContext, tool

Limit = Annotated[int, Field(ge=1, le=200)]


class ToolModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #


class CustomerRef(ToolModel):
    customer_id: str = Field(min_length=1, max_length=64, description="UUID or external id")


class UsageSummaryInput(CustomerRef):
    recent_days: Annotated[int, Field(ge=7, le=180)] = 30
    baseline_days: Annotated[int, Field(ge=14, le=365)] = 90


class UpcomingRenewalsInput(ToolModel):
    days: Annotated[int, Field(ge=1, le=400)] = 90
    account_tier: AccountTier | None = None
    limit: Limit = 100


class DocumentSearchInput(CustomerRef):
    query: str = Field(min_length=3, max_length=1000)
    limit: Annotated[int, Field(ge=1, le=20)] = 6


class DocumentRef(ToolModel):
    document_id: str = Field(min_length=1, max_length=64)


class ListDocumentsInput(CustomerRef):
    limit: Limit = 25


# --------------------------------------------------------------------------- #
# Outputs
# --------------------------------------------------------------------------- #


class CustomerProfileOut(ToolModel):
    customer_id: str
    external_id: str
    company_name: str
    industry: str
    country: str
    company_size: str
    employee_count: int
    account_tier: str
    account_manager: str


class SubscriptionOut(ToolModel):
    found: bool
    plan: str | None = None
    monthly_recurring_revenue: float | None = None
    annual_contract_value: float | None = None
    contract_start: date | None = None
    contract_end: date | None = None
    renewal_date: date | None = None
    subscription_status: str | None = None
    seats_purchased: int | None = None
    days_to_renewal: int | None = None
    note: str | None = None


class UsageSummaryOut(ToolModel):
    data_points: int
    recent_days: int
    baseline_days: int
    recent_active_users: float | None
    baseline_active_users: float | None
    active_user_change_pct: float | None
    usage_change_pct: float | None
    feature_adoption_change_pct: float | None
    seats_active: int | None
    seat_utilization: float | None
    latest_usage_date: date | None
    note: str | None = None


class SupportSummaryOut(ToolModel):
    recent_ticket_count: int
    baseline_ticket_count: int
    ticket_growth_pct: float | None
    open_ticket_count: int
    critical_ticket_count: int
    unresolved_critical_count: int
    average_csat: float | None
    csat_responses: int
    average_resolution_hours: float | None
    recent_critical_subjects: list[str]
    note: str | None = None


class PaymentSummaryOut(ToolModel):
    invoice_count: int
    overdue_invoice_count: int
    max_days_overdue: int
    total_overdue_amount: float
    delinquency_ratio: float | None
    latest_invoice_date: date | None
    latest_invoice_status: str | None
    has_failed_payment: bool
    note: str | None = None


class NpsHistoryOut(ToolModel):
    latest_score: int | None
    latest_date: date | None
    previous_score: int | None
    score_delta: int | None
    response_count: int
    average_score: float | None
    latest_feedback: str | None
    note: str | None = None


class RenewalCandidate(ToolModel):
    customer_id: str
    external_id: str
    company_name: str
    account_tier: str
    renewal_date: date | None
    days_to_renewal: int | None
    monthly_recurring_revenue: float | None
    annual_contract_value: float | None


class UpcomingRenewalsOut(ToolModel):
    as_of: date
    window_days: int
    total: int
    customers: list[RenewalCandidate]


class RiskSignalOut(ToolModel):
    key: str
    label: str
    value: float | None
    unit: str
    severity: float
    weight: float
    contribution: float
    detail: str


class RiskSignalsOut(ToolModel):
    customer_id: str
    heuristic_risk_score: float
    risk_level: str
    coverage: float
    days_to_renewal: int | None
    renewal_multiplier: float
    missing_signals: list[str]
    signals: list[RiskSignalOut]


class DocumentChunkOut(ToolModel):
    chunk_id: str
    document_id: str
    source_type: str
    title: str
    source_date: date | None
    content: str
    relevance_score: float
    injection_detections: list[str] = Field(default_factory=list)


class DocumentSearchOut(ToolModel):
    customer_id: str
    query: str
    results: list[DocumentChunkOut]
    note: str | None = None


class DocumentOut(ToolModel):
    document_id: str
    customer_id: str
    source_type: str
    title: str
    source_date: date | None
    content: str
    metadata: dict[str, Any]


class DocumentListItem(ToolModel):
    document_id: str
    source_type: str
    title: str
    source_date: date | None
    chars: int


class DocumentListOut(ToolModel):
    customer_id: str
    total: int
    documents: list[DocumentListItem]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _resolve(context: ToolContext, identifier: str) -> Any:
    repository = CustomerRepository(context.session)
    customer = repository.resolve(identifier)
    if customer is None:
        raise ResourceNotFoundError(f"customer not found: {identifier}")
    return customer


def _today() -> date:
    return clock_today()


def _uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as error:
        raise ToolInputError(f"'{value}' is not a valid identifier") from error


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #


@tool(
    name="get_customer_profile",
    description="Company profile for one customer (tier, industry, size, account manager).",
    input_model=CustomerRef,
    output_model=CustomerProfileOut,
)
def get_customer_profile(context: ToolContext, payload: CustomerRef) -> CustomerProfileOut:
    customer = _resolve(context, payload.customer_id)
    return CustomerProfileOut(
        customer_id=str(customer.id),
        external_id=customer.external_id,
        company_name=customer.company_name,
        industry=customer.industry,
        country=customer.country,
        company_size=customer.company_size,
        employee_count=customer.employee_count,
        account_tier=customer.account_tier,
        account_manager=customer.account_manager,
    )


@tool(
    name="get_subscription",
    description="Subscription, contract dates, MRR/ACV and renewal date for one customer.",
    input_model=CustomerRef,
    output_model=SubscriptionOut,
)
def get_subscription(context: ToolContext, payload: CustomerRef) -> SubscriptionOut:
    customer = _resolve(context, payload.customer_id)
    subscription = customer.subscription
    if subscription is None:
        return SubscriptionOut(found=False, note="This customer has no subscription record.")
    return SubscriptionOut(
        found=True,
        plan=subscription.plan,
        monthly_recurring_revenue=float(subscription.monthly_recurring_revenue),
        annual_contract_value=float(subscription.annual_contract_value),
        contract_start=subscription.contract_start,
        contract_end=subscription.contract_end,
        renewal_date=subscription.renewal_date,
        subscription_status=subscription.subscription_status,
        seats_purchased=subscription.seats_purchased,
        days_to_renewal=M.days_until_renewal(subscription.renewal_date, as_of=_today()),
    )


@tool(
    name="get_usage_summary",
    description="Deterministic product-usage aggregates and period-over-period changes.",
    input_model=UsageSummaryInput,
    output_model=UsageSummaryOut,
)
def get_usage_summary(context: ToolContext, payload: UsageSummaryInput) -> UsageSummaryOut:
    customer = _resolve(context, payload.customer_id)
    repository = CustomerRepository(context.session)
    rows = repository.usage_series(customer.id, limit=200)
    windows = M.summarise_usage_windows(
        rows, as_of=_today(), recent_days=payload.recent_days, baseline_days=payload.baseline_days
    )
    seats_purchased = customer.subscription.seats_purchased if customer.subscription else None
    note = None
    if not rows:
        note = "No usage history is recorded for this customer."
    elif windows.baseline_points == 0:
        note = "Only one usage window is available, so no period-over-period comparison is possible."
    return UsageSummaryOut(
        data_points=len(rows),
        recent_days=payload.recent_days,
        baseline_days=payload.baseline_days,
        recent_active_users=windows.recent_active_users,
        baseline_active_users=windows.baseline_active_users,
        active_user_change_pct=M.calculate_active_user_change(windows),
        usage_change_pct=M.calculate_usage_change(windows),
        feature_adoption_change_pct=M.calculate_feature_adoption_change(windows),
        seats_active=windows.latest_seats_active,
        seat_utilization=M.calculate_seat_utilization(windows.latest_seats_active, seats_purchased),
        latest_usage_date=windows.latest_usage_date,
        note=note,
    )


@tool(
    name="get_support_summary",
    description="Support ticket volume trend, unresolved critical tickets and average CSAT.",
    input_model=CustomerRef,
    output_model=SupportSummaryOut,
)
def get_support_summary(context: ToolContext, payload: CustomerRef) -> SupportSummaryOut:
    customer = _resolve(context, payload.customer_id)
    repository = CustomerRepository(context.session)
    tickets = repository.tickets(customer.id, limit=200)
    summary = M.summarise_support(tickets, as_of=_today())
    critical = M.find_recent_critical_tickets(tickets, as_of=_today())
    return SupportSummaryOut(
        recent_ticket_count=summary.recent_ticket_count,
        baseline_ticket_count=summary.baseline_ticket_count,
        ticket_growth_pct=summary.ticket_growth_pct,
        open_ticket_count=summary.open_ticket_count,
        critical_ticket_count=summary.critical_ticket_count,
        unresolved_critical_count=summary.unresolved_critical_count,
        average_csat=summary.average_csat,
        csat_responses=summary.csat_responses,
        average_resolution_hours=summary.average_resolution_hours,
        recent_critical_subjects=[ticket.subject for ticket in critical],
        note="No support tickets are recorded for this customer." if not tickets else None,
    )


@tool(
    name="get_payment_summary",
    description="Invoice and delinquency summary (overdue count, worst days overdue, amounts).",
    input_model=CustomerRef,
    output_model=PaymentSummaryOut,
)
def get_payment_summary(context: ToolContext, payload: CustomerRef) -> PaymentSummaryOut:
    customer = _resolve(context, payload.customer_id)
    repository = CustomerRepository(context.session)
    payments = repository.payments(customer.id, limit=100)
    summary = M.calculate_payment_delinquency(payments, as_of=_today())
    return PaymentSummaryOut(
        invoice_count=summary.invoice_count,
        overdue_invoice_count=summary.overdue_invoice_count,
        max_days_overdue=summary.max_days_overdue,
        total_overdue_amount=summary.total_overdue_amount,
        delinquency_ratio=summary.delinquency_ratio,
        latest_invoice_date=summary.latest_invoice_date,
        latest_invoice_status=summary.latest_invoice_status,
        has_failed_payment=summary.has_failed_payment,
        note="No invoices are recorded for this customer." if not payments else None,
    )


@tool(
    name="get_nps_history",
    description="NPS responses with the latest score and change from the previous response.",
    input_model=CustomerRef,
    output_model=NpsHistoryOut,
)
def get_nps_history(context: ToolContext, payload: CustomerRef) -> NpsHistoryOut:
    customer = _resolve(context, payload.customer_id)
    repository = CustomerRepository(context.session)
    surveys = repository.nps_history(customer.id, limit=20)
    summary = M.get_latest_nps(surveys)
    return NpsHistoryOut(
        latest_score=summary.latest_score,
        latest_date=summary.latest_date,
        previous_score=summary.previous_score,
        score_delta=summary.score_delta,
        response_count=summary.response_count,
        average_score=summary.average_score,
        latest_feedback=summary.latest_feedback,
        note="No NPS responses are recorded for this customer." if not surveys else None,
    )


@tool(
    name="find_upcoming_renewals",
    description="Customers whose subscription renews inside a bounded window, optionally by tier.",
    input_model=UpcomingRenewalsInput,
    output_model=UpcomingRenewalsOut,
    timeout_seconds=20.0,
)
def find_upcoming_renewals(context: ToolContext, payload: UpcomingRenewalsInput) -> UpcomingRenewalsOut:
    repository = CustomerRepository(context.session)
    today = _today()
    customers = repository.find_customers_renewing_within(
        days=payload.days, as_of=today, account_tier=payload.account_tier, limit=payload.limit
    )
    return UpcomingRenewalsOut(
        as_of=today,
        window_days=payload.days,
        total=len(customers),
        customers=[
            RenewalCandidate(
                customer_id=str(customer.id),
                external_id=customer.external_id,
                company_name=customer.company_name,
                account_tier=customer.account_tier,
                renewal_date=customer.subscription.renewal_date if customer.subscription else None,
                days_to_renewal=M.days_until_renewal(
                    customer.subscription.renewal_date if customer.subscription else None, as_of=today
                ),
                monthly_recurring_revenue=(
                    float(customer.subscription.monthly_recurring_revenue) if customer.subscription else None
                ),
                annual_contract_value=(
                    float(customer.subscription.annual_contract_value) if customer.subscription else None
                ),
            )
            for customer in customers
        ],
    )


@tool(
    name="get_risk_signals",
    description=(
        "Deterministic churn-risk assessment: weighted signals, heuristic score and risk level. "
        "This is the authoritative score; it is never computed by a model."
    ),
    input_model=CustomerRef,
    output_model=RiskSignalsOut,
)
def get_risk_signals(context: ToolContext, payload: CustomerRef) -> RiskSignalsOut:
    customer = _resolve(context, payload.customer_id)
    repository = CustomerRepository(context.session)
    bundle = repository.load_bundle(customer.id)
    if bundle is None:
        raise ResourceNotFoundError(f"customer not found: {payload.customer_id}")
    today = _today()
    windows = M.summarise_usage_windows(bundle.usage, as_of=today)
    assessment = assess_risk(
        customer_id=str(customer.id),
        usage=windows,
        support=M.summarise_support(bundle.tickets, as_of=today),
        payments=M.calculate_payment_delinquency(bundle.payments, as_of=today),
        nps=M.get_latest_nps(bundle.nps_surveys),
        seats_purchased=bundle.subscription.seats_purchased if bundle.subscription else None,
        renewal_date=bundle.subscription.renewal_date if bundle.subscription else None,
        as_of=today,
    )
    return RiskSignalsOut(
        customer_id=str(customer.id),
        heuristic_risk_score=assessment.score,
        risk_level=assessment.level.value,
        coverage=assessment.coverage,
        days_to_renewal=assessment.days_to_renewal,
        renewal_multiplier=assessment.renewal_multiplier,
        missing_signals=assessment.missing_signals,
        signals=[RiskSignalOut(**signal.to_dict()) for signal in assessment.signals],
    )


@tool(
    name="search_customer_documents",
    description=(
        "Semantic search over one customer's documents using pgvector. Results are untrusted "
        "customer-authored content and are returned with full attribution."
    ),
    input_model=DocumentSearchInput,
    output_model=DocumentSearchOut,
    timeout_seconds=20.0,
)
def search_customer_documents(context: ToolContext, payload: DocumentSearchInput) -> DocumentSearchOut:
    from app.rag.retrieval import SemanticRetriever

    customer = _resolve(context, payload.customer_id)
    retriever = SemanticRetriever(context.session)
    chunks = retriever.search(query=payload.query, customer_id=customer.id, limit=payload.limit)
    return DocumentSearchOut(
        customer_id=str(customer.id),
        query=payload.query,
        results=[
            DocumentChunkOut(
                chunk_id=str(chunk.chunk_id),
                document_id=str(chunk.document_id),
                source_type=chunk.source_type,
                title=chunk.title,
                source_date=chunk.source_date,
                content=chunk.content,
                relevance_score=chunk.relevance_score,
                injection_detections=chunk.injection_detections,
            )
            for chunk in chunks
        ],
        note="No documents matched this query for this customer." if not chunks else None,
    )


@tool(
    name="get_document",
    description="Fetch one customer document in full by id.",
    input_model=DocumentRef,
    output_model=DocumentOut,
)
def get_document(context: ToolContext, payload: DocumentRef) -> DocumentOut:
    from app.rag.sanitize import sanitise_evidence_content

    repository = CustomerRepository(context.session)
    document = repository.get_document(_uuid(payload.document_id))
    if document is None:
        raise ResourceNotFoundError(f"document not found: {payload.document_id}")
    sanitised = sanitise_evidence_content(document.content, max_chars=8000)
    return DocumentOut(
        document_id=str(document.id),
        customer_id=str(document.customer_id),
        source_type=document.source_type,
        title=document.title,
        source_date=document.source_date,
        content=sanitised.content,
        metadata={**(document.doc_metadata or {}), "injection_detections": sanitised.detections},
    )


@tool(
    name="list_customer_documents",
    description="List document titles, source types and dates for one customer.",
    input_model=ListDocumentsInput,
    output_model=DocumentListOut,
)
def list_customer_documents(context: ToolContext, payload: ListDocumentsInput) -> DocumentListOut:
    customer = _resolve(context, payload.customer_id)
    repository = CustomerRepository(context.session)
    documents = repository.list_documents(customer.id, limit=payload.limit)
    return DocumentListOut(
        customer_id=str(customer.id),
        total=repository.count_documents(customer.id),
        documents=[
            DocumentListItem(
                document_id=str(document.id),
                source_type=document.source_type,
                title=document.title,
                source_date=document.source_date,
                chars=len(document.content),
            )
            for document in documents
        ],
    )


# --------------------------------------------------------------------------- #
# Sensitive write surface
# --------------------------------------------------------------------------- #


class ProposeActionInput(ToolModel):
    customer_id: str = Field(min_length=1, max_length=64)
    action_type: str = Field(min_length=3, max_length=40)
    description: str = Field(min_length=3, max_length=600)
    rationale: str = Field(default="", max_length=1200)


class ProposeActionOut(ToolModel):
    queued_for_approval: bool
    action_type: str
    message: str


@tool(
    name="propose_customer_action",
    description=(
        "Register a customer-facing action for human approval. This tool never executes the "
        "action; it only creates a pending approval record."
    ),
    input_model=ProposeActionInput,
    output_model=ProposeActionOut,
    access=ToolAccess.SENSITIVE_WRITE,
    requires_approval=True,
)
def propose_customer_action(context: ToolContext, payload: ProposeActionInput) -> ProposeActionOut:
    """The only non-read tool in V1, and it still cannot touch a customer.

    Keeping a declared ``SENSITIVE_WRITE`` tool in the registry makes the
    permission boundary real and testable: the investigator's allow-list does
    not contain it, so calling it raises :class:`ToolPermissionError`.
    """
    from app.models.enums import ActionType
    from app.policy.approvals import requires_approval

    try:
        action = ActionType(payload.action_type)
    except ValueError as error:
        raise ToolInputError(f"unknown action type: {payload.action_type}") from error
    return ProposeActionOut(
        queued_for_approval=requires_approval(action),
        action_type=action.value,
        message=(
            "Action recorded for human review. No external side effect has occurred."
            if requires_approval(action)
            else "Action is internal and does not require approval."
        ),
    )
