"""Deterministic metric calculations, including the null and zero cases."""

from __future__ import annotations

from datetime import date

import pytest

from app.analytics import metrics as M
from tests.conftest import nps_row, payment_row, ticket_row, usage_row

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Usage windows
# --------------------------------------------------------------------------- #


def test_usage_windows_split_recent_and_baseline_without_overlap(as_of: date) -> None:
    rows = [
        *(usage_row(days_ago=day, active_users=40, as_of=as_of) for day in (7, 14, 21, 28)),
        *(usage_row(days_ago=day, active_users=80, as_of=as_of) for day in (35, 49, 63, 84)),
    ]
    windows = M.summarise_usage_windows(rows, as_of=as_of)

    assert windows.recent_points == 4
    assert windows.baseline_points == 4
    assert windows.recent_active_users == 40
    assert windows.baseline_active_users == 80
    # A halving of DAU must read as -50%, not as a blended -25%.
    assert M.calculate_active_user_change(windows) == pytest.approx(-50.0)


def test_usage_change_falls_back_to_api_calls_when_sessions_are_absent(as_of: date) -> None:
    rows = [
        usage_row(days_ago=10, active_users=10, sessions=0, api_calls=100, as_of=as_of),
        usage_row(days_ago=50, active_users=10, sessions=0, api_calls=400, as_of=as_of),
    ]
    windows = M.summarise_usage_windows(rows, as_of=as_of)
    # Sessions are all zero, so the zero-baseline rule yields 0.0 rather than
    # None, and the API-call signal is what carries information.
    assert windows.recent_sessions == 0
    assert M.calculate_usage_change(windows) == pytest.approx(0.0)

    rows_without_sessions = [
        usage_row(days_ago=10, active_users=10, sessions=None, api_calls=100, as_of=as_of),
    ]
    single = M.summarise_usage_windows(rows_without_sessions, as_of=as_of)
    assert M.calculate_usage_change(single) is None


def test_no_usage_history_yields_none_not_zero(as_of: date) -> None:
    windows = M.summarise_usage_windows([], as_of=as_of)
    assert windows.recent_points == 0
    assert windows.baseline_points == 0
    assert M.calculate_active_user_change(windows) is None
    assert M.calculate_usage_change(windows) is None
    assert windows.latest_usage_date is None


def test_single_usage_point_has_no_comparable_baseline(as_of: date) -> None:
    windows = M.summarise_usage_windows([usage_row(days_ago=3, active_users=12, as_of=as_of)], as_of=as_of)
    assert windows.recent_points == 1
    assert windows.baseline_points == 0
    assert M.calculate_active_user_change(windows) is None


def test_zero_baseline_with_growth_is_reported_as_capped_increase(as_of: date) -> None:
    rows = [
        usage_row(days_ago=5, active_users=25, as_of=as_of),
        usage_row(days_ago=60, active_users=0, as_of=as_of),
    ]
    windows = M.summarise_usage_windows(rows, as_of=as_of)
    # Not infinity, and never a crash.
    assert M.calculate_active_user_change(windows) == pytest.approx(100.0)


def test_rows_with_missing_dates_are_ignored(as_of: date) -> None:
    good = usage_row(days_ago=5, active_users=10, as_of=as_of)
    bad = usage_row(days_ago=5, active_users=999, as_of=as_of)
    bad.usage_date = None
    windows = M.summarise_usage_windows([good, bad], as_of=as_of)
    assert windows.recent_points == 1
    assert windows.recent_active_users == 10


# --------------------------------------------------------------------------- #
# Seat utilisation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("active", "purchased", "expected"),
    [
        (40, 100, 0.4),
        (100, 100, 1.0),
        (120, 100, 1.2),  # over-provisioned usage is reported, not clamped
        (0, 100, 0.0),
    ],
)
def test_seat_utilization(active: int, purchased: int, expected: float) -> None:
    assert M.calculate_seat_utilization(active, purchased) == pytest.approx(expected)


def test_seat_utilization_with_zero_seats_is_unknown_not_zero() -> None:
    """Zero purchased seats means "no seat model", not "0% utilisation"."""
    assert M.calculate_seat_utilization(10, 0) is None
    assert M.calculate_seat_utilization(10, None) is None
    assert M.calculate_seat_utilization(None, 50) is None


# --------------------------------------------------------------------------- #
# Support
# --------------------------------------------------------------------------- #


def test_ticket_growth_normalises_window_lengths(as_of: date) -> None:
    """A flat ticket rate must read as ~0% growth, not +100%.

    The baseline window is 60 days and the recent window 30, so comparing raw
    counts would make a steady account look like it doubled.
    """
    tickets = [
        *(ticket_row(days_ago=day, as_of=as_of) for day in (5, 15, 25)),
        *(ticket_row(days_ago=day, as_of=as_of) for day in (35, 45, 55, 65, 75, 85)),
    ]
    summary = M.summarise_support(tickets, as_of=as_of)
    assert summary.recent_ticket_count == 3
    assert summary.baseline_ticket_count == 6
    assert summary.ticket_growth_pct == pytest.approx(0.0)


def test_ticket_growth_detects_a_real_spike(as_of: date) -> None:
    tickets = [
        *(ticket_row(days_ago=day, as_of=as_of) for day in (2, 4, 6, 8, 10, 12, 14, 16, 18)),
        *(ticket_row(days_ago=day, as_of=as_of) for day in (40, 70)),
    ]
    summary = M.summarise_support(tickets, as_of=as_of)
    # 9 recent vs 2 over 60 days (= 1 normalised per 30 days) → +800%.
    assert summary.ticket_growth_pct == pytest.approx(800.0)


def test_no_tickets_is_zero_growth_not_unknown(as_of: date) -> None:
    summary = M.summarise_support([], as_of=as_of)
    assert summary.recent_ticket_count == 0
    assert summary.ticket_growth_pct == pytest.approx(0.0)
    assert summary.average_csat is None
    assert summary.csat_responses == 0
    assert summary.unresolved_critical_count == 0


def test_first_ever_tickets_report_capped_growth(as_of: date) -> None:
    summary = M.summarise_support([ticket_row(days_ago=3, as_of=as_of)], as_of=as_of)
    assert summary.ticket_growth_pct == pytest.approx(100.0)


def test_unresolved_critical_tickets_are_counted_separately(as_of: date) -> None:
    tickets = [
        ticket_row(days_ago=2, priority="CRITICAL", status="ESCALATED", csat=None, resolution_hours=None, as_of=as_of),
        ticket_row(days_ago=4, priority="HIGH", status="OPEN", csat=None, resolution_hours=None, as_of=as_of),
        ticket_row(days_ago=6, priority="HIGH", status="RESOLVED", as_of=as_of),
        ticket_row(days_ago=8, priority="LOW", status="OPEN", csat=None, resolution_hours=None, as_of=as_of),
    ]
    summary = M.summarise_support(tickets, as_of=as_of)
    assert summary.critical_ticket_count == 3
    assert summary.unresolved_critical_count == 2
    assert summary.escalated_ticket_count == 1
    assert summary.open_ticket_count == 3


def test_average_csat_ignores_tickets_without_a_response(as_of: date) -> None:
    tickets = [
        ticket_row(days_ago=1, csat=2.0, as_of=as_of),
        ticket_row(days_ago=2, csat=4.0, as_of=as_of),
        ticket_row(days_ago=3, csat=None, as_of=as_of),
    ]
    assert M.calculate_average_csat(tickets) == pytest.approx(3.0)
    assert M.summarise_support(tickets, as_of=as_of).csat_responses == 2


def test_find_recent_critical_tickets_is_bounded_and_ordered(as_of: date) -> None:
    tickets = [
        ticket_row(days_ago=day, priority="CRITICAL", subject=f"day-{day}", as_of=as_of)
        for day in (1, 5, 10, 20, 30, 40, 100)
    ]
    found = M.find_recent_critical_tickets(tickets, as_of=as_of, days=60, limit=3)
    assert [t.subject for t in found] == ["day-1", "day-5", "day-10"]


# --------------------------------------------------------------------------- #
# Payments
# --------------------------------------------------------------------------- #


def test_payment_delinquency_summarises_overdue_invoices(as_of: date) -> None:
    payments = [
        payment_row(days_ago=10, payment_status="OVERDUE", days_overdue=38, paid=False, as_of=as_of),
        payment_row(days_ago=40, payment_status="PAID", as_of=as_of),
        payment_row(days_ago=70, payment_status="PAID", as_of=as_of),
    ]
    summary = M.calculate_payment_delinquency(payments, as_of=as_of)
    assert summary.invoice_count == 3
    assert summary.overdue_invoice_count == 1
    assert summary.max_days_overdue == 38
    assert summary.delinquency_ratio == pytest.approx(1 / 3, abs=1e-4)
    assert summary.has_failed_payment is False


def test_unpaid_invoice_without_a_due_date_is_still_counted(as_of: date) -> None:
    """Real billing exports contain invoices with no due date; the status is
    authoritative and must not be discarded."""
    payments = [
        payment_row(
            days_ago=20,
            payment_status="OVERDUE",
            days_overdue=25,
            paid=False,
            due_date_offset=None,
            as_of=as_of,
        )
    ]
    summary = M.calculate_payment_delinquency(payments, as_of=as_of)
    assert summary.overdue_invoice_count == 1
    assert summary.max_days_overdue == 25
    assert payments[0].due_date is None


def test_pending_invoice_past_due_contributes_days_overdue(as_of: date) -> None:
    payments = [payment_row(days_ago=45, payment_status="PENDING", days_overdue=14, paid=False, as_of=as_of)]
    summary = M.calculate_payment_delinquency(payments, as_of=as_of)
    assert summary.overdue_invoice_count == 0
    assert summary.max_days_overdue == 14


def test_failed_payment_is_flagged(as_of: date) -> None:
    payments = [payment_row(days_ago=5, payment_status="FAILED", days_overdue=5, paid=False, as_of=as_of)]
    assert M.calculate_payment_delinquency(payments, as_of=as_of).has_failed_payment is True


def test_no_payments_leaves_ratio_unknown(as_of: date) -> None:
    summary = M.calculate_payment_delinquency([], as_of=as_of)
    assert summary.invoice_count == 0
    assert summary.delinquency_ratio is None
    assert summary.max_days_overdue == 0
    assert summary.latest_invoice_date is None


# --------------------------------------------------------------------------- #
# NPS
# --------------------------------------------------------------------------- #


def test_latest_nps_picks_the_newest_and_computes_the_delta(as_of: date) -> None:
    surveys = [
        nps_row(days_ago=180, score=8, as_of=as_of),
        nps_row(days_ago=20, score=3, feedback="Reporting gaps", as_of=as_of),
        nps_row(days_ago=400, score=9, as_of=as_of),
    ]
    summary = M.get_latest_nps(surveys)
    assert summary.latest_score == 3
    assert summary.previous_score == 8
    assert summary.score_delta == -5
    assert summary.response_count == 3
    assert summary.latest_feedback == "Reporting gaps"


def test_single_nps_response_has_no_delta(as_of: date) -> None:
    summary = M.get_latest_nps([nps_row(days_ago=10, score=7, as_of=as_of)])
    assert summary.latest_score == 7
    assert summary.previous_score is None
    assert summary.score_delta is None


def test_no_nps_responses_is_fully_unknown() -> None:
    summary = M.get_latest_nps([])
    assert summary.latest_score is None
    assert summary.average_score is None
    assert summary.response_count == 0
    assert summary.score_delta is None


def test_nps_score_of_zero_is_a_value_not_a_missing_reading(as_of: date) -> None:
    """0 is the worst possible NPS, not "no data" — a falsy-value bug here would
    silently drop the strongest negative signal in the dataset."""
    summary = M.get_latest_nps([nps_row(days_ago=1, score=0, as_of=as_of)])
    assert summary.latest_score == 0
    assert summary.average_score == pytest.approx(0.0)


# --------------------------------------------------------------------------- #
# Renewal timing
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("renewal", "expected"),
    [
        (date(2026, 6, 30), 29),
        (date(2026, 6, 1), 0),
        (date(2026, 5, 1), -31),
    ],
)
def test_days_until_renewal(renewal: date, expected: int, as_of: date) -> None:
    assert M.days_until_renewal(renewal, as_of=as_of) == expected


def test_days_until_renewal_without_a_date() -> None:
    assert M.days_until_renewal(None, as_of=date(2026, 6, 1)) is None
