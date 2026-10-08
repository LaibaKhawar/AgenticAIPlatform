"""Baseline risk engine: scoring, missing data, bounds and the LLM blend band."""

from __future__ import annotations

from datetime import date

import pytest

from app.analytics import metrics as M
from app.analytics.risk import (
    DOMINANT_SHARE,
    WEIGHTED_SHARE,
    WEIGHTS,
    assess_risk,
    blend_scores,
    formula_documentation,
    renewal_multiplier,
    risk_level_for,
)
from app.models.enums import RiskLevel
from tests.conftest import nps_row, payment_row, ticket_row, usage_row

pytestmark = pytest.mark.unit


def _assess(
    *,
    as_of: date,
    usage_rows: list | None = None,
    tickets: list | None = None,
    payments: list | None = None,
    surveys: list | None = None,
    seats_purchased: int | None = 100,
    renewal_date: date | None = None,
):
    windows = M.summarise_usage_windows(usage_rows or [], as_of=as_of)
    return assess_risk(
        customer_id="c-1",
        usage=windows,
        support=M.summarise_support(tickets or [], as_of=as_of),
        payments=M.calculate_payment_delinquency(payments or [], as_of=as_of),
        nps=M.get_latest_nps(surveys or []),
        seats_purchased=seats_purchased,
        renewal_date=renewal_date,
        as_of=as_of,
    )


def _healthy_usage(as_of: date) -> list:
    return [
        *(usage_row(days_ago=day, active_users=80, seats_active=80, as_of=as_of) for day in (5, 12, 19, 26)),
        *(usage_row(days_ago=day, active_users=80, seats_active=80, as_of=as_of) for day in (40, 55, 70, 85)),
    ]


def _collapsing_usage(as_of: date) -> list:
    return [
        *(usage_row(days_ago=day, active_users=20, seats_active=20, adoption=30, as_of=as_of) for day in (5, 12, 19, 26)),
        *(usage_row(days_ago=day, active_users=90, seats_active=90, adoption=70, as_of=as_of) for day in (40, 55, 70, 85)),
    ]


# --------------------------------------------------------------------------- #
# Weights and documentation
# --------------------------------------------------------------------------- #


def test_component_weights_sum_to_one() -> None:
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)


def test_aggregation_shares_sum_to_one() -> None:
    assert pytest.approx(1.0) == WEIGHTED_SHARE + DOMINANT_SHARE


def test_formula_documentation_does_not_claim_to_be_a_trained_model() -> None:
    doc = formula_documentation()
    assert doc["is_trained_model"] is False
    assert doc["model_type"] == "transparent_weighted_heuristic"
    assert set(doc["weights"]) == set(WEIGHTS)
    assert "not a trained" in doc["description"].lower()


# --------------------------------------------------------------------------- #
# Scoring behaviour
# --------------------------------------------------------------------------- #


def test_healthy_account_scores_low(as_of: date) -> None:
    assessment = _assess(
        as_of=as_of,
        usage_rows=_healthy_usage(as_of),
        tickets=[ticket_row(days_ago=day, csat=4.8, as_of=as_of) for day in (10, 40, 70)],
        payments=[payment_row(days_ago=day, as_of=as_of) for day in (10, 40, 70)],
        surveys=[nps_row(days_ago=20, score=9, as_of=as_of)],
        renewal_date=date(2026, 12, 1),
    )
    assert assessment.score < 20
    assert assessment.level is RiskLevel.LOW
    assert assessment.coverage == pytest.approx(1.0)
    assert assessment.missing_signals == []


def test_account_with_every_signal_failing_scores_critical(as_of: date) -> None:
    assessment = _assess(
        as_of=as_of,
        usage_rows=_collapsing_usage(as_of),
        tickets=[
            *(
                ticket_row(days_ago=day, priority="CRITICAL", status="ESCALATED", csat=1.0, resolution_hours=None, as_of=as_of)
                for day in (1, 3, 5, 7, 9, 11)
            ),
            ticket_row(days_ago=70, as_of=as_of, csat=2.0),
        ],
        payments=[
            payment_row(days_ago=5, payment_status="OVERDUE", days_overdue=60, paid=False, as_of=as_of),
            payment_row(days_ago=40, payment_status="OVERDUE", days_overdue=40, paid=False, as_of=as_of),
        ],
        surveys=[nps_row(days_ago=120, score=8, as_of=as_of), nps_row(days_ago=10, score=1, as_of=as_of)],
        renewal_date=as_of.replace(day=20),
        seats_purchased=100,
    )
    assert assessment.score >= 75
    assert assessment.level is RiskLevel.CRITICAL


def test_single_severe_signal_reaches_medium_on_its_own(as_of: date) -> None:
    """A 78% collapse in active users with everything else healthy is a real
    escalation. A pure weighted average would bury it; the dominant-signal term
    is what lets it surface."""
    assessment = _assess(
        as_of=as_of,
        usage_rows=[
            *(usage_row(days_ago=day, active_users=20, seats_active=20, as_of=as_of) for day in (5, 12, 19, 26)),
            *(usage_row(days_ago=day, active_users=90, seats_active=90, as_of=as_of) for day in (40, 55, 70, 85)),
        ],
        tickets=[ticket_row(days_ago=day, csat=4.6, as_of=as_of) for day in (10, 40, 70)],
        payments=[payment_row(days_ago=day, as_of=as_of) for day in (10, 40, 70)],
        surveys=[nps_row(days_ago=15, score=9, as_of=as_of)],
        renewal_date=date(2026, 7, 15),
    )
    assert assessment.score >= 40, f"single severe signal scored only {assessment.score}"
    assert assessment.level in {RiskLevel.MEDIUM, RiskLevel.HIGH}
    top = assessment.top_signals[0]
    assert top.key in {"active_user_decline", "seat_utilization", "usage_decline"}


def test_missing_data_is_renormalised_not_treated_as_healthy(as_of: date) -> None:
    """An account with only one bad signal and no other data must not be
    diluted towards zero by the absent components."""
    assessment = _assess(
        as_of=as_of,
        usage_rows=_collapsing_usage(as_of),
        tickets=[],
        payments=[],
        surveys=[],
        seats_purchased=None,
        renewal_date=as_of,
    )
    assert "nps" in assessment.missing_signals
    assert "payment_delinquency" in assessment.missing_signals
    assert "seat_utilization" in assessment.missing_signals
    assert assessment.coverage < 1.0
    # Usage signals carry the whole score, so it must still be elevated.
    assert assessment.score > 45


def test_empty_customer_scores_zero_with_no_coverage(as_of: date) -> None:
    assessment = _assess(as_of=as_of, seats_purchased=None, renewal_date=None)
    # Support with no tickets legitimately reads as "no pressure", so coverage
    # is not zero — but the score is.
    assert assessment.score == pytest.approx(0.0)
    assert assessment.level is RiskLevel.LOW
    assert assessment.signals != []


def test_score_is_always_within_bounds(as_of: date) -> None:
    assessment = _assess(
        as_of=as_of,
        usage_rows=_collapsing_usage(as_of),
        tickets=[
            ticket_row(days_ago=d, priority="CRITICAL", status="OPEN", csat=1.0, resolution_hours=None, as_of=as_of)
            for d in range(1, 25)
        ],
        payments=[payment_row(days_ago=1, payment_status="FAILED", days_overdue=400, paid=False, as_of=as_of)],
        surveys=[nps_row(days_ago=100, score=10, as_of=as_of), nps_row(days_ago=1, score=0, as_of=as_of)],
        renewal_date=as_of,
    )
    assert 0.0 <= assessment.score <= 100.0
    for signal in assessment.signals:
        assert 0.0 <= signal.severity <= 1.0


def test_growth_never_produces_a_negative_contribution(as_of: date) -> None:
    """A thriving signal must not subsidise a failing one down to zero."""
    assessment = _assess(
        as_of=as_of,
        usage_rows=[
            *(usage_row(days_ago=day, active_users=160, seats_active=95, as_of=as_of) for day in (5, 12, 19, 26)),
            *(usage_row(days_ago=day, active_users=80, seats_active=70, as_of=as_of) for day in (40, 55, 70, 85)),
        ],
        tickets=[ticket_row(days_ago=1, priority="CRITICAL", status="OPEN", csat=1.0, resolution_hours=None, as_of=as_of)],
        renewal_date=as_of,
    )
    contributions = {signal.key: signal.contribution for signal in assessment.signals}
    assert all(value >= 0 for value in contributions.values())
    assert contributions["active_user_decline"] == pytest.approx(0.0)


# --------------------------------------------------------------------------- #
# Renewal urgency
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("days", "expected"),
    [(5, 1.18), (30, 1.18), (31, 1.10), (60, 1.10), (75, 1.04), (120, 1.00), (400, 0.94), (None, 1.0)],
)
def test_renewal_multiplier_buckets(days: int | None, expected: float) -> None:
    assert renewal_multiplier(days) == pytest.approx(expected)


def test_overdue_renewal_is_treated_as_most_urgent() -> None:
    assert renewal_multiplier(-10) == pytest.approx(1.18)


def test_renewal_proximity_raises_the_score_for_identical_health(as_of: date) -> None:
    def score_for(renewal: date) -> float:
        return _assess(
            as_of=as_of,
            usage_rows=_collapsing_usage(as_of),
            tickets=[ticket_row(days_ago=5, csat=3.0, as_of=as_of)],
            payments=[payment_row(days_ago=5, as_of=as_of)],
            surveys=[nps_row(days_ago=5, score=5, as_of=as_of)],
            renewal_date=renewal,
        ).score

    assert score_for(date(2026, 6, 15)) > score_for(date(2027, 6, 15))


# --------------------------------------------------------------------------- #
# Levels and the agent blend band
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("score", "level"),
    [
        (0.0, RiskLevel.LOW),
        (39.9, RiskLevel.LOW),
        (40.0, RiskLevel.MEDIUM),
        (59.9, RiskLevel.MEDIUM),
        (60.0, RiskLevel.HIGH),
        (74.9, RiskLevel.HIGH),
        (75.0, RiskLevel.CRITICAL),
        (100.0, RiskLevel.CRITICAL),
    ],
)
def test_risk_level_thresholds(score: float, level: RiskLevel) -> None:
    assert risk_level_for(score) is level


def test_blend_scores_clamps_an_agent_that_tries_to_invent_a_score() -> None:
    assert blend_scores(50.0, 99.0) == pytest.approx(65.0)
    assert blend_scores(50.0, 1.0) == pytest.approx(35.0)


def test_blend_scores_accepts_small_agent_adjustments() -> None:
    assert blend_scores(50.0, 56.0) == pytest.approx(56.0)


def test_blend_scores_falls_back_to_the_heuristic() -> None:
    assert blend_scores(42.5, None) == pytest.approx(42.5)


def test_blend_scores_never_leaves_the_valid_range() -> None:
    assert blend_scores(97.0, 500.0) == pytest.approx(100.0)
    assert blend_scores(3.0, -500.0) == pytest.approx(0.0)
