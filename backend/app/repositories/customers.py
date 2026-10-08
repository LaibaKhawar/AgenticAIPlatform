"""Customer data access.

All agent-facing reads go through validated repository methods — there is no
path by which a model-authored SQL string reaches the database. Batch helpers
exist specifically to avoid N+1 queries when a run screens hundreds of
candidates at once.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.domain import (
    Customer,
    CustomerDocument,
    CustomerOutcomeRecord,
    DocumentChunk,
    NpsSurvey,
    Payment,
    ProductUsage,
    Subscription,
    SupportTicket,
)
from app.models.enums import AccountTier, CustomerOutcome, SubscriptionStatus


@dataclass(frozen=True)
class CustomerFilter:
    search: str | None = None
    account_tier: AccountTier | None = None
    industry: str | None = None
    renewal_within_days: int | None = None
    subscription_status: SubscriptionStatus | None = None
    outcome: CustomerOutcome | None = None
    min_mrr: float | None = None


@dataclass(frozen=True)
class CustomerBundle:
    """Everything the deterministic analytics layer needs for one customer."""

    customer: Customer
    subscription: Subscription | None
    usage: list[ProductUsage]
    tickets: list[SupportTicket]
    payments: list[Payment]
    nps_surveys: list[NpsSurvey]
    outcome: CustomerOutcomeRecord | None


class CustomerRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # --- single customer --------------------------------------------------

    def get(self, customer_id: uuid.UUID) -> Customer | None:
        return self.session.get(Customer, customer_id)

    def get_with_subscription(self, customer_id: uuid.UUID) -> Customer | None:
        return self.session.scalars(
            select(Customer)
            .options(selectinload(Customer.subscription), selectinload(Customer.outcome))
            .where(Customer.id == customer_id)
        ).first()

    def get_by_external_id(self, external_id: str) -> Customer | None:
        return self.session.scalars(
            select(Customer)
            .options(selectinload(Customer.subscription), selectinload(Customer.outcome))
            .where(Customer.external_id == external_id)
        ).first()

    def resolve(self, identifier: str) -> Customer | None:
        """Accept either a UUID or an external id (``CUST-000123``)."""
        try:
            parsed = uuid.UUID(identifier)
        except (ValueError, AttributeError, TypeError):
            return self.get_by_external_id(identifier)
        return self.get_with_subscription(parsed)

    # --- collections ------------------------------------------------------

    def _base_query(self, filters: CustomerFilter, *, as_of: date) -> Select[Customer]:
        query = select(Customer).join(Subscription, isouter=True)
        if filters.search:
            pattern = f"%{filters.search.strip()}%"
            query = query.where(or_(Customer.company_name.ilike(pattern), Customer.external_id.ilike(pattern)))
        if filters.account_tier:
            query = query.where(Customer.account_tier == filters.account_tier.value)
        if filters.industry:
            query = query.where(Customer.industry == filters.industry)
        if filters.subscription_status:
            query = query.where(Subscription.subscription_status == filters.subscription_status.value)
        if filters.renewal_within_days is not None:
            horizon = as_of + timedelta(days=filters.renewal_within_days)
            query = query.where(Subscription.renewal_date >= as_of, Subscription.renewal_date <= horizon)
        if filters.min_mrr is not None:
            query = query.where(Subscription.monthly_recurring_revenue >= filters.min_mrr)
        if filters.outcome:
            query = query.join(CustomerOutcomeRecord).where(CustomerOutcomeRecord.outcome == filters.outcome.value)
        return query

    def count(self, filters: CustomerFilter, *, as_of: date) -> int:
        query = self._base_query(filters, as_of=as_of)
        return int(self.session.scalar(select(func.count()).select_from(query.subquery())) or 0)

    def list_customers(
        self, filters: CustomerFilter, *, as_of: date, limit: int = 50, offset: int = 0
    ) -> list[Customer]:
        query = (
            self._base_query(filters, as_of=as_of)
            .options(selectinload(Customer.subscription), selectinload(Customer.outcome))
            .order_by(Subscription.renewal_date.asc().nullslast(), Customer.company_name.asc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.scalars(query).unique())

    def find_customers_renewing_within(
        self,
        *,
        days: int,
        as_of: date,
        account_tier: AccountTier | None = None,
        limit: int = 200,
        only_active: bool = True,
    ) -> list[Customer]:
        """Candidate generation: deterministic, indexed, and bounded."""
        horizon = as_of + timedelta(days=days)
        query = (
            select(Customer)
            .join(Subscription)
            .options(selectinload(Customer.subscription))
            .where(Subscription.renewal_date >= as_of, Subscription.renewal_date <= horizon)
        )
        if only_active:
            query = query.where(
                Subscription.subscription_status.in_(
                    [SubscriptionStatus.ACTIVE.value, SubscriptionStatus.PAST_DUE.value]
                )
            )
        if account_tier:
            query = query.where(Customer.account_tier == account_tier.value)
        query = query.order_by(Subscription.renewal_date.asc()).limit(limit)
        return list(self.session.scalars(query).unique())

    def list_industries(self) -> list[str]:
        return list(self.session.scalars(select(Customer.industry).distinct().order_by(Customer.industry)))

    # --- related rows (batched) ------------------------------------------

    def load_bundles(
        self, customer_ids: Sequence[uuid.UUID], *, usage_since: date | None = None, tickets_since: date | None = None
    ) -> dict[uuid.UUID, CustomerBundle]:
        """Load everything for many customers using one query per relation.

        Five queries total regardless of how many customers are screened; the
        naive per-customer version would issue 5N.
        """
        if not customer_ids:
            return {}
        ids = list(customer_ids)

        customers = list(
            self.session.scalars(
                select(Customer)
                .options(selectinload(Customer.subscription), selectinload(Customer.outcome))
                .where(Customer.id.in_(ids))
            ).unique()
        )

        usage_query = select(ProductUsage).where(ProductUsage.customer_id.in_(ids))
        if usage_since is not None:
            usage_query = usage_query.where(ProductUsage.usage_date >= usage_since)
        usage_rows = list(self.session.scalars(usage_query.order_by(ProductUsage.usage_date)))

        ticket_query = select(SupportTicket).where(SupportTicket.customer_id.in_(ids))
        if tickets_since is not None:
            ticket_query = ticket_query.where(SupportTicket.created_at >= tickets_since)
        ticket_rows = list(self.session.scalars(ticket_query.order_by(SupportTicket.created_at)))

        payment_rows = list(
            self.session.scalars(select(Payment).where(Payment.customer_id.in_(ids)).order_by(Payment.invoice_date))
        )
        nps_rows = list(
            self.session.scalars(
                select(NpsSurvey).where(NpsSurvey.customer_id.in_(ids)).order_by(NpsSurvey.response_date)
            )
        )

        grouped_usage: dict[uuid.UUID, list[ProductUsage]] = {cid: [] for cid in ids}
        grouped_tickets: dict[uuid.UUID, list[SupportTicket]] = {cid: [] for cid in ids}
        grouped_payments: dict[uuid.UUID, list[Payment]] = {cid: [] for cid in ids}
        grouped_nps: dict[uuid.UUID, list[NpsSurvey]] = {cid: [] for cid in ids}
        for usage in usage_rows:
            grouped_usage.setdefault(usage.customer_id, []).append(usage)
        for ticket in ticket_rows:
            grouped_tickets.setdefault(ticket.customer_id, []).append(ticket)
        for payment in payment_rows:
            grouped_payments.setdefault(payment.customer_id, []).append(payment)
        for survey in nps_rows:
            grouped_nps.setdefault(survey.customer_id, []).append(survey)

        return {
            customer.id: CustomerBundle(
                customer=customer,
                subscription=customer.subscription,
                usage=grouped_usage.get(customer.id, []),
                tickets=grouped_tickets.get(customer.id, []),
                payments=grouped_payments.get(customer.id, []),
                nps_surveys=grouped_nps.get(customer.id, []),
                outcome=customer.outcome,
            )
            for customer in customers
        }

    def load_bundle(self, customer_id: uuid.UUID, **kwargs: Any) -> CustomerBundle | None:
        return self.load_bundles([customer_id], **kwargs).get(customer_id)

    def usage_series(
        self, customer_id: uuid.UUID, *, since: date | None = None, limit: int = 180
    ) -> list[ProductUsage]:
        query = select(ProductUsage).where(ProductUsage.customer_id == customer_id)
        if since is not None:
            query = query.where(ProductUsage.usage_date >= since)
        return list(self.session.scalars(query.order_by(ProductUsage.usage_date.desc()).limit(limit)))[::-1]

    def tickets(self, customer_id: uuid.UUID, *, limit: int = 50) -> list[SupportTicket]:
        return list(
            self.session.scalars(
                select(SupportTicket)
                .where(SupportTicket.customer_id == customer_id)
                .order_by(SupportTicket.created_at.desc())
                .limit(limit)
            )
        )

    def payments(self, customer_id: uuid.UUID, *, limit: int = 50) -> list[Payment]:
        return list(
            self.session.scalars(
                select(Payment)
                .where(Payment.customer_id == customer_id)
                .order_by(Payment.invoice_date.desc())
                .limit(limit)
            )
        )

    def nps_history(self, customer_id: uuid.UUID, *, limit: int = 20) -> list[NpsSurvey]:
        return list(
            self.session.scalars(
                select(NpsSurvey)
                .where(NpsSurvey.customer_id == customer_id)
                .order_by(NpsSurvey.response_date.desc())
                .limit(limit)
            )
        )

    # --- documents --------------------------------------------------------

    def list_documents(self, customer_id: uuid.UUID, *, limit: int = 50, offset: int = 0) -> list[CustomerDocument]:
        return list(
            self.session.scalars(
                select(CustomerDocument)
                .where(CustomerDocument.customer_id == customer_id)
                .order_by(CustomerDocument.source_date.desc())
                .limit(limit)
                .offset(offset)
            )
        )

    def count_documents(self, customer_id: uuid.UUID) -> int:
        return int(
            self.session.scalar(
                select(func.count()).select_from(CustomerDocument).where(CustomerDocument.customer_id == customer_id)
            )
            or 0
        )

    def get_document(self, document_id: uuid.UUID) -> CustomerDocument | None:
        return self.session.get(CustomerDocument, document_id)

    def get_chunk(self, chunk_id: uuid.UUID) -> DocumentChunk | None:
        return self.session.get(DocumentChunk, chunk_id)

    # --- aggregate statistics --------------------------------------------

    def portfolio_stats(self, *, as_of: date) -> dict[str, Any]:
        total = int(self.session.scalar(select(func.count()).select_from(Customer)) or 0)
        documents = int(self.session.scalar(select(func.count()).select_from(CustomerDocument)) or 0)
        chunks = int(self.session.scalar(select(func.count()).select_from(DocumentChunk)) or 0)
        embedded = int(
            self.session.scalar(
                select(func.count()).select_from(DocumentChunk).where(DocumentChunk.embedding.isnot(None))
            )
            or 0
        )
        renewing_90 = int(
            self.session.scalar(
                select(func.count())
                .select_from(Subscription)
                .where(
                    Subscription.renewal_date >= as_of,
                    Subscription.renewal_date <= as_of + timedelta(days=90),
                )
            )
            or 0
        )
        outcome_rows = self.session.execute(
            select(CustomerOutcomeRecord.outcome, func.count()).group_by(CustomerOutcomeRecord.outcome)
        ).all()
        tier_rows = self.session.execute(
            select(Customer.account_tier, func.count()).group_by(Customer.account_tier)
        ).all()
        arr = float(self.session.scalar(select(func.coalesce(func.sum(Subscription.annual_contract_value), 0))) or 0)
        return {
            "total_customers": total,
            "documents": documents,
            "document_chunks": chunks,
            "embedded_chunks": embedded,
            "renewing_within_90_days": renewing_90,
            "outcomes": {str(outcome): int(count) for outcome, count in outcome_rows},
            "tiers": {str(tier): int(count) for tier, count in tier_rows},
            "total_acv": round(arr, 2),
        }

    def historical_outcome_customers(
        self, *, outcomes: Sequence[CustomerOutcome], limit: int = 1000
    ) -> list[uuid.UUID]:
        """Customer ids with a known historical outcome (evaluation dataset)."""
        return list(
            self.session.scalars(
                select(CustomerOutcomeRecord.customer_id)
                .where(CustomerOutcomeRecord.outcome.in_([o.value for o in outcomes]))
                .order_by(CustomerOutcomeRecord.customer_id)
                .limit(limit)
            )
        )
