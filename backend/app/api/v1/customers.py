"""Customer endpoints."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.analytics import metrics as M
from app.analytics.risk import assess_risk, formula_documentation
from app.api.deps import DbSession, Pagination
from app.core.clock import today as clock_today
from app.models.domain import CustomerDocument, DocumentChunk
from app.models.enums import AccountTier, CustomerOutcome, SubscriptionStatus
from app.rag.sanitize import sanitise_evidence_content
from app.repositories.customers import CustomerFilter, CustomerRepository
from app.repositories.investigations import InvestigationRepository
from app.schemas.api import (
    CustomerDetailResponse,
    CustomerListItem,
    CustomerRiskResponse,
    DocumentDetail,
    DocumentListItem,
    InvestigationHistoryItem,
    NpsResponseItem,
    Page,
    PaymentSummaryItem,
    RiskSignalItem,
    SubscriptionSummary,
    TicketSummary,
    UsagePoint,
)

router = APIRouter(prefix="/customers", tags=["customers"])


def _to_list_item(customer: Any, *, as_of: date) -> CustomerListItem:
    subscription = None
    if customer.subscription is not None:
        subscription = SubscriptionSummary(
            plan=customer.subscription.plan,
            monthly_recurring_revenue=float(customer.subscription.monthly_recurring_revenue),
            annual_contract_value=float(customer.subscription.annual_contract_value),
            contract_start=customer.subscription.contract_start,
            contract_end=customer.subscription.contract_end,
            renewal_date=customer.subscription.renewal_date,
            subscription_status=customer.subscription.subscription_status,
            seats_purchased=customer.subscription.seats_purchased,
            days_to_renewal=M.days_until_renewal(customer.subscription.renewal_date, as_of=as_of),
        )
    return CustomerListItem(
        id=customer.id,
        external_id=customer.external_id,
        company_name=customer.company_name,
        industry=customer.industry,
        country=customer.country,
        account_tier=customer.account_tier,
        account_manager=customer.account_manager,
        employee_count=customer.employee_count,
        subscription=subscription,
        outcome=customer.outcome.outcome if customer.outcome else None,
    )


def _resolve_or_404(repository: CustomerRepository, identifier: str) -> Any:
    customer = repository.resolve(identifier)
    if customer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "not_found",
                    "message": f"No customer matches '{identifier}'.",
                }
            },
        )
    return customer


def _risk_response(session: Any, customer: Any, *, as_of: date) -> CustomerRiskResponse:
    repository = CustomerRepository(session)
    bundle = repository.load_bundle(customer.id)
    assert bundle is not None
    windows = M.summarise_usage_windows(bundle.usage, as_of=as_of)
    assessment = assess_risk(
        customer_id=str(customer.id),
        usage=windows,
        support=M.summarise_support(bundle.tickets, as_of=as_of),
        payments=M.calculate_payment_delinquency(bundle.payments, as_of=as_of),
        nps=M.get_latest_nps(bundle.nps_surveys),
        seats_purchased=bundle.subscription.seats_purchased if bundle.subscription else None,
        renewal_date=bundle.subscription.renewal_date if bundle.subscription else None,
        as_of=as_of,
    )
    return CustomerRiskResponse(
        customer_id=customer.id,
        external_id=customer.external_id,
        company_name=customer.company_name,
        heuristic_risk_score=assessment.score,
        risk_level=assessment.level,
        coverage=assessment.coverage,
        days_to_renewal=assessment.days_to_renewal,
        renewal_multiplier=assessment.renewal_multiplier,
        missing_signals=assessment.missing_signals,
        signals=[RiskSignalItem(**signal.to_dict()) for signal in assessment.signals],
        model=formula_documentation(),
    )


@router.get("", response_model=Page[CustomerListItem], summary="List customers")
def list_customers(
    session: DbSession,
    page: Pagination,
    search: Annotated[str | None, Query(max_length=200)] = None,
    account_tier: AccountTier | None = None,
    industry: Annotated[str | None, Query(max_length=80)] = None,
    subscription_status: SubscriptionStatus | None = None,
    outcome: CustomerOutcome | None = None,
    renewal_within_days: Annotated[int | None, Query(ge=1, le=400)] = None,
    min_mrr: Annotated[float | None, Query(ge=0)] = None,
) -> Page[CustomerListItem]:
    today = clock_today()
    repository = CustomerRepository(session)
    filters = CustomerFilter(
        search=search,
        account_tier=account_tier,
        industry=industry,
        subscription_status=subscription_status,
        outcome=outcome,
        renewal_within_days=renewal_within_days,
        min_mrr=min_mrr,
    )
    total = repository.count(filters, as_of=today)
    customers = repository.list_customers(filters, as_of=today, limit=page.limit, offset=page.offset)
    return Page[CustomerListItem](
        items=[_to_list_item(customer, as_of=today) for customer in customers],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/industries", response_model=list[str], summary="Distinct industries")
def list_industries(session: DbSession) -> list[str]:
    return CustomerRepository(session).list_industries()


@router.get("/{customer_id}", response_model=CustomerDetailResponse, summary="Customer detail")
def get_customer(customer_id: str, session: DbSession) -> CustomerDetailResponse:
    today = clock_today()
    repository = CustomerRepository(session)
    customer = _resolve_or_404(repository, customer_id)

    usage_rows = repository.usage_series(customer.id, since=today - timedelta(days=180))
    tickets = repository.tickets(customer.id, limit=50)
    payments = repository.payments(customer.id, limit=24)
    surveys = repository.nps_history(customer.id, limit=12)
    documents = repository.list_documents(customer.id, limit=50)

    chunk_counts = dict(
        session.execute(
            select(DocumentChunk.document_id, func.count())
            .where(DocumentChunk.document_id.in_([document.id for document in documents] or [uuid.uuid4()]))
            .group_by(DocumentChunk.document_id)
        ).all()
    )

    windows = M.summarise_usage_windows(usage_rows, as_of=today)
    support = M.summarise_support(tickets, as_of=today)
    payment_summary = M.calculate_payment_delinquency(payments, as_of=today)
    nps_summary = M.get_latest_nps(surveys)
    seats = customer.subscription.seats_purchased if customer.subscription else None

    investigations = InvestigationRepository(session).history_for_customer(customer.id, limit=10)

    return CustomerDetailResponse(
        customer=_to_list_item(customer, as_of=today),
        usage=[UsagePoint.model_validate(row) for row in usage_rows],
        usage_summary={
            "data_points": len(usage_rows),
            "recent_active_users": windows.recent_active_users,
            "baseline_active_users": windows.baseline_active_users,
            "active_user_change_pct": M.calculate_active_user_change(windows),
            "usage_change_pct": M.calculate_usage_change(windows),
            "feature_adoption_change_pct": M.calculate_feature_adoption_change(windows),
            "seat_utilization": M.calculate_seat_utilization(windows.latest_seats_active, seats),
            "seats_active": windows.latest_seats_active,
            "seats_purchased": seats,
            "latest_usage_date": windows.latest_usage_date,
        },
        tickets=[TicketSummary.model_validate(ticket) for ticket in tickets],
        support_summary={
            "recent_ticket_count": support.recent_ticket_count,
            "baseline_ticket_count": support.baseline_ticket_count,
            "ticket_growth_pct": support.ticket_growth_pct,
            "open_ticket_count": support.open_ticket_count,
            "critical_ticket_count": support.critical_ticket_count,
            "unresolved_critical_count": support.unresolved_critical_count,
            "average_csat": support.average_csat,
            "csat_responses": support.csat_responses,
            "average_resolution_hours": support.average_resolution_hours,
        },
        payments=[PaymentSummaryItem.model_validate(payment) for payment in payments],
        payment_summary={
            "invoice_count": payment_summary.invoice_count,
            "overdue_invoice_count": payment_summary.overdue_invoice_count,
            "max_days_overdue": payment_summary.max_days_overdue,
            "total_overdue_amount": payment_summary.total_overdue_amount,
            "delinquency_ratio": payment_summary.delinquency_ratio,
            "latest_invoice_status": payment_summary.latest_invoice_status,
            "has_failed_payment": payment_summary.has_failed_payment,
        },
        nps=[NpsResponseItem.model_validate(survey) for survey in surveys],
        nps_summary={
            "latest_score": nps_summary.latest_score,
            "previous_score": nps_summary.previous_score,
            "score_delta": nps_summary.score_delta,
            "average_score": nps_summary.average_score,
            "response_count": nps_summary.response_count,
            "latest_feedback": nps_summary.latest_feedback,
        },
        documents=[
            DocumentListItem(
                id=document.id,
                source_type=document.source_type,
                title=document.title,
                source_date=document.source_date,
                chars=len(document.content),
                chunk_count=int(chunk_counts.get(document.id, 0)),
            )
            for document in documents
        ],
        risk=_risk_response(session, customer, as_of=today),
        outcome=(
            {
                "outcome": customer.outcome.outcome,
                "outcome_date": customer.outcome.outcome_date,
                "churn_reason": customer.outcome.churn_reason,
                "notes": customer.outcome.notes,
            }
            if customer.outcome
            else None
        ),
        investigations=[
            InvestigationHistoryItem(
                id=investigation.id,
                run_id=investigation.run_id,
                risk_score=float(investigation.risk_score),
                risk_level=investigation.risk_level,
                confidence=float(investigation.confidence),
                summary=investigation.summary,
                created_at=investigation.created_at,
            )
            for investigation in investigations
        ],
    )


@router.get("/{customer_id}/usage", response_model=list[UsagePoint], summary="Usage time series")
def get_usage(
    customer_id: str,
    session: DbSession,
    days: Annotated[int, Query(ge=7, le=365)] = 180,
) -> list[UsagePoint]:
    repository = CustomerRepository(session)
    customer = _resolve_or_404(repository, customer_id)
    rows = repository.usage_series(customer.id, since=clock_today() - timedelta(days=days))
    return [UsagePoint.model_validate(row) for row in rows]


@router.get(
    "/{customer_id}/documents",
    response_model=Page[DocumentListItem],
    summary="Customer documents",
)
def list_documents(customer_id: str, session: DbSession, page: Pagination) -> Page[DocumentListItem]:
    repository = CustomerRepository(session)
    customer = _resolve_or_404(repository, customer_id)
    documents = repository.list_documents(customer.id, limit=page.limit, offset=page.offset)
    return Page[DocumentListItem](
        items=[
            DocumentListItem(
                id=document.id,
                source_type=document.source_type,
                title=document.title,
                source_date=document.source_date,
                chars=len(document.content),
            )
            for document in documents
        ],
        total=repository.count_documents(customer.id),
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/{customer_id}/documents/{document_id}",
    response_model=DocumentDetail,
    summary="One customer document",
)
def get_document(customer_id: str, document_id: str, session: DbSession) -> DocumentDetail:
    repository = CustomerRepository(session)
    customer = _resolve_or_404(repository, customer_id)
    try:
        parsed = uuid.UUID(document_id)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "not_found", "message": "Unknown document id."}},
        ) from error

    document = session.get(CustomerDocument, parsed)
    if document is None or document.customer_id != customer.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "not_found",
                    "message": "This document does not exist for this customer.",
                }
            },
        )
    sanitised = sanitise_evidence_content(document.content, max_chars=20000)
    return DocumentDetail(
        id=document.id,
        customer_id=document.customer_id,
        source_type=document.source_type,
        title=document.title,
        source_date=document.source_date,
        content=sanitised.content,
        metadata={
            **(document.doc_metadata or {}),
            "injection_detections": sanitised.detections,
            "content_is_untrusted": True,
        },
    )


@router.get("/{customer_id}/risk", response_model=CustomerRiskResponse, summary="Deterministic risk signals")
def get_risk(customer_id: str, session: DbSession) -> CustomerRiskResponse:
    repository = CustomerRepository(session)
    customer = _resolve_or_404(repository, customer_id)
    return _risk_response(session, customer, as_of=clock_today())
