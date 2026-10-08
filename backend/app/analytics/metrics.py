"""Deterministic customer metrics.

Every number an agent is allowed to state as a *calculated metric* is produced
here, in plain Python, from rows read out of PostgreSQL. No LLM computes
arithmetic, dates or rankings anywhere in this system.

All functions are pure and null-tolerant: a customer with no usage history, no
tickets, no payments or no NPS response must produce a well-formed result with
``None`` values rather than an exception, because the synthetic dataset (and
real data) contains exactly those gaps.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from app.models.enums import PaymentStatus, TicketPriority, TicketStatus

CRITICAL_PRIORITIES = {TicketPriority.HIGH, TicketPriority.CRITICAL}
UNRESOLVED_STATUSES = {TicketStatus.OPEN, TicketStatus.PENDING, TicketStatus.ESCALATED}


# --------------------------------------------------------------------------- #
# Row protocols: plain attribute access so these helpers work with ORM rows,
# dataclasses or test doubles alike.
# --------------------------------------------------------------------------- #


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _pct_change(previous: float | None, current: float | None) -> float | None:
    """Percentage change from ``previous`` to ``current`` (-100.0 == gone).

    Returns ``None`` when there is no usable baseline; a zero baseline with
    positive current value is reported as +100.0 rather than infinity.
    """
    if previous is None or current is None:
        return None
    if previous == 0:
        return 0.0 if current == 0 else 100.0
    return round((current - previous) / abs(previous) * 100.0, 2)


def _mean(values: Sequence[float]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


# --------------------------------------------------------------------------- #
# Usage
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class WindowedUsage:
    """Usage aggregates for a recent window and the preceding baseline window."""

    recent_days: int
    baseline_days: int
    recent_points: int
    baseline_points: int
    recent_active_users: float | None
    baseline_active_users: float | None
    recent_sessions: float | None
    baseline_sessions: float | None
    recent_api_calls: float | None
    baseline_api_calls: float | None
    recent_feature_adoption: float | None
    baseline_feature_adoption: float | None
    latest_seats_active: int | None
    latest_usage_date: date | None


def summarise_usage_windows(
    usage_rows: Iterable[Any], *, as_of: date, recent_days: int = 30, baseline_days: int = 90
) -> WindowedUsage:
    """Split usage rows into a recent window and the preceding baseline window.

    The baseline is the ``[as_of - baseline_days, as_of - recent_days)`` span, so
    "30-day average vs. the 60 days before that" — not an overlapping window,
    which would dampen a real decline.
    """
    recent_cutoff = as_of - timedelta(days=recent_days)
    baseline_cutoff = as_of - timedelta(days=baseline_days)

    recent: list[Any] = []
    baseline: list[Any] = []
    latest_row: Any | None = None
    latest_date: date | None = None

    for row in usage_rows:
        row_date = _as_date(getattr(row, "usage_date", None))
        if row_date is None:
            continue
        if latest_date is None or row_date > latest_date:
            latest_row = row
            latest_date = row_date
        if row_date > recent_cutoff:
            recent.append(row)
        elif baseline_cutoff <= row_date <= recent_cutoff:
            baseline.append(row)

    def avg(rows: list[Any], field: str) -> float | None:
        values = [float(getattr(row, field)) for row in rows if getattr(row, field, None) is not None]
        return _mean(values)

    return WindowedUsage(
        recent_days=recent_days,
        baseline_days=baseline_days,
        recent_points=len(recent),
        baseline_points=len(baseline),
        recent_active_users=avg(recent, "active_users"),
        baseline_active_users=avg(baseline, "active_users"),
        recent_sessions=avg(recent, "sessions"),
        baseline_sessions=avg(baseline, "sessions"),
        recent_api_calls=avg(recent, "api_calls"),
        baseline_api_calls=avg(baseline, "api_calls"),
        recent_feature_adoption=avg(recent, "feature_adoption_score"),
        baseline_feature_adoption=avg(baseline, "feature_adoption_score"),
        latest_seats_active=int(latest_row.seats_active) if latest_row is not None else None,
        latest_usage_date=latest_date,
    )


def calculate_active_user_change(windows: WindowedUsage) -> float | None:
    """Percent change in average daily active users (recent vs. baseline)."""
    return _pct_change(windows.baseline_active_users, windows.recent_active_users)


def calculate_usage_change(windows: WindowedUsage) -> float | None:
    """Percent change in product usage intensity.

    Uses sessions when available and falls back to API calls, so an account that
    reports only one of the two still produces a signal.
    """
    sessions = _pct_change(windows.baseline_sessions, windows.recent_sessions)
    if sessions is not None:
        return sessions
    return _pct_change(windows.baseline_api_calls, windows.recent_api_calls)


def calculate_feature_adoption_change(windows: WindowedUsage) -> float | None:
    return _pct_change(windows.baseline_feature_adoption, windows.recent_feature_adoption)


def calculate_seat_utilization(seats_active: int | None, seats_purchased: int | None) -> float | None:
    """Fraction of purchased seats in active use (0.0-1.0+).

    ``None`` when seats were never purchased — dividing by zero seats would
    otherwise invent a 0% utilisation signal for a usage-based contract.
    """
    if seats_active is None or not seats_purchased:
        return None
    return round(seats_active / seats_purchased, 4)


# --------------------------------------------------------------------------- #
# Support
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SupportSummary:
    recent_ticket_count: int
    baseline_ticket_count: int
    ticket_growth_pct: float | None
    open_ticket_count: int
    critical_ticket_count: int
    escalated_ticket_count: int
    average_csat: float | None
    csat_responses: int
    average_resolution_hours: float | None
    unresolved_critical_count: int
    last_ticket_date: date | None


def summarise_support(
    tickets: Iterable[Any], *, as_of: date, recent_days: int = 30, baseline_days: int = 90
) -> SupportSummary:
    recent_cutoff = as_of - timedelta(days=recent_days)
    baseline_cutoff = as_of - timedelta(days=baseline_days)

    recent = 0
    baseline = 0
    open_count = 0
    critical = 0
    escalated = 0
    unresolved_critical = 0
    csat_values: list[float] = []
    resolution_values: list[float] = []
    last_date: date | None = None

    for ticket in tickets:
        created = _as_date(getattr(ticket, "created_at", None))
        if created is not None:
            if last_date is None or created > last_date:
                last_date = created
            if created > recent_cutoff:
                recent += 1
            elif baseline_cutoff <= created <= recent_cutoff:
                baseline += 1

        status = getattr(ticket, "status", None)
        priority = getattr(ticket, "priority", None)
        if status in UNRESOLVED_STATUSES:
            open_count += 1
        if status == TicketStatus.ESCALATED:
            escalated += 1
        if priority in CRITICAL_PRIORITIES:
            critical += 1
            if status in UNRESOLVED_STATUSES:
                unresolved_critical += 1

        csat = getattr(ticket, "csat_score", None)
        if csat is not None:
            csat_values.append(float(csat))
        hours = getattr(ticket, "resolution_hours", None)
        if hours is not None:
            resolution_values.append(float(hours))

    # Normalise the baseline window to the same length as the recent window so
    # "90-day total vs 30-day total" cannot masquerade as a 200% spike.
    baseline_scale = (baseline_days - recent_days) / recent_days if baseline_days > recent_days else 1.0
    normalised_baseline = baseline / baseline_scale if baseline_scale else float(baseline)

    return SupportSummary(
        recent_ticket_count=recent,
        baseline_ticket_count=baseline,
        ticket_growth_pct=calculate_ticket_growth(normalised_baseline, recent),
        open_ticket_count=open_count,
        critical_ticket_count=critical,
        escalated_ticket_count=escalated,
        average_csat=_mean(csat_values),
        csat_responses=len(csat_values),
        average_resolution_hours=_mean(resolution_values),
        unresolved_critical_count=unresolved_critical,
        last_ticket_date=last_date,
    )


def calculate_ticket_growth(baseline_count: float | None, recent_count: int | None) -> float | None:
    """Percent change in ticket volume between comparable windows."""
    if recent_count is None:
        return None
    if baseline_count is None:
        return None
    if baseline_count == 0:
        # No tickets before, some tickets now: a real but unbounded signal.
        # Report a capped value so downstream scoring stays well defined.
        return 100.0 if recent_count > 0 else 0.0
    return round((recent_count - baseline_count) / baseline_count * 100.0, 2)


def calculate_average_csat(tickets: Iterable[Any]) -> float | None:
    values = [float(ticket.csat_score) for ticket in tickets if getattr(ticket, "csat_score", None) is not None]
    return _mean(values)


def find_recent_critical_tickets(tickets: Iterable[Any], *, as_of: date, days: int = 60, limit: int = 5) -> list[Any]:
    cutoff = as_of - timedelta(days=days)
    selected = [
        ticket
        for ticket in tickets
        if getattr(ticket, "priority", None) in CRITICAL_PRIORITIES
        and (_as_date(getattr(ticket, "created_at", None)) or date.min) > cutoff
    ]
    selected.sort(key=lambda t: _as_date(t.created_at) or date.min, reverse=True)
    return selected[:limit]


# --------------------------------------------------------------------------- #
# Payments
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PaymentSummary:
    invoice_count: int
    overdue_invoice_count: int
    max_days_overdue: int
    total_overdue_amount: float
    delinquency_ratio: float | None
    latest_invoice_date: date | None
    latest_invoice_status: str | None
    has_failed_payment: bool


def calculate_payment_delinquency(payments: Iterable[Any], *, as_of: date | None = None) -> PaymentSummary:
    """Summarise billing health.

    Invoices missing a due date are still counted when their status says they
    are overdue — the status is authoritative, the date is best-effort.
    """
    invoices = list(payments)
    overdue = 0
    max_overdue = 0
    overdue_amount = 0.0
    failed = False
    latest: Any | None = None
    latest_date: date | None = None

    for invoice in invoices:
        status = getattr(invoice, "payment_status", None)
        days = int(getattr(invoice, "days_overdue", 0) or 0)
        if status in {PaymentStatus.OVERDUE, PaymentStatus.FAILED, PaymentStatus.WRITTEN_OFF}:
            overdue += 1
            overdue_amount += float(getattr(invoice, "amount", 0) or 0)
            max_overdue = max(max_overdue, days)
        elif days > 0 and getattr(invoice, "payment_date", None) is None:
            # Pending past its due date without an explicit OVERDUE status.
            max_overdue = max(max_overdue, days)
        if status == PaymentStatus.FAILED:
            failed = True
        invoice_date = _as_date(getattr(invoice, "invoice_date", None))
        if invoice_date is not None and (latest_date is None or invoice_date > latest_date):
            latest = invoice
            latest_date = invoice_date

    return PaymentSummary(
        invoice_count=len(invoices),
        overdue_invoice_count=overdue,
        max_days_overdue=max_overdue,
        total_overdue_amount=round(overdue_amount, 2),
        delinquency_ratio=round(overdue / len(invoices), 4) if invoices else None,
        latest_invoice_date=latest_date,
        latest_invoice_status=str(getattr(latest, "payment_status", "")) if latest else None,
        has_failed_payment=failed,
    )


# --------------------------------------------------------------------------- #
# NPS
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class NpsSummary:
    latest_score: int | None
    latest_date: date | None
    previous_score: int | None
    score_delta: int | None
    response_count: int
    average_score: float | None
    latest_feedback: str | None


def get_latest_nps(surveys: Iterable[Any]) -> NpsSummary:
    ordered = sorted(
        (survey for survey in surveys if _as_date(getattr(survey, "response_date", None))),
        key=lambda s: _as_date(s.response_date) or date.min,
        reverse=True,
    )
    if not ordered:
        return NpsSummary(None, None, None, None, 0, None, None)

    latest = ordered[0]
    previous = ordered[1] if len(ordered) > 1 else None
    latest_score = int(latest.score)
    previous_score = int(previous.score) if previous is not None else None
    return NpsSummary(
        latest_score=latest_score,
        latest_date=_as_date(latest.response_date),
        previous_score=previous_score,
        score_delta=(latest_score - previous_score) if previous_score is not None else None,
        response_count=len(ordered),
        average_score=_mean([float(s.score) for s in ordered]),
        latest_feedback=getattr(latest, "feedback", None) or None,
    )


# --------------------------------------------------------------------------- #
# Contract timing
# --------------------------------------------------------------------------- #


def days_until_renewal(renewal_date: date | None, *, as_of: date) -> int | None:
    """Days until renewal; negative when the renewal date has passed."""
    if renewal_date is None:
        return None
    return (renewal_date - as_of).days
