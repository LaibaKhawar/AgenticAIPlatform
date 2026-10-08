"""Baseline heuristic churn-risk score.

This is a **transparent weighted heuristic**, not a trained predictive model.
Nothing here was fitted on data; the weights encode a customer-success analyst's
prior about which signals matter, and the evaluation harness
(:mod:`app.evaluation`) measures how well that prior ranks historical outcomes.

Score = 100 * Σ(weight_i · component_i) over the components whose inputs are
available, renormalised by the weight that was actually usable. Components are
each squashed into 0..1 where 1 means "maximum concern".

    component                     weight   drives
    --------------------------------------------------------------------
    active_user_decline            0.22    30d vs 60d-prior avg DAU
    usage_decline                  0.14    sessions (or API calls) change
    support_pressure               0.14    ticket growth + unresolved critical
    csat                           0.10    average CSAT (1-5)
    nps                            0.12    latest NPS (0-10) and its drop
    payment_delinquency            0.12    overdue invoices / days overdue
    seat_utilization               0.08    active seats / purchased seats
    feature_adoption_decline       0.08    adoption-score change
    --------------------------------------------------------------------
    renewal proximity is a *multiplier*, not a component: the same health
    signals are more urgent 20 days before a renewal than 300 days before.

The score is used for candidate generation and ranking only. Qualitative
interpretation is the LLM investigator's job, and the investigator may move the
final score within a bounded band (see ``blend_scores``) but cannot invent one.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from app.analytics.metrics import (
    NpsSummary,
    PaymentSummary,
    SupportSummary,
    WindowedUsage,
    calculate_active_user_change,
    calculate_feature_adoption_change,
    calculate_seat_utilization,
    calculate_usage_change,
    days_until_renewal,
)
from app.core.config import get_settings
from app.models.enums import RiskLevel

WEIGHTS: dict[str, float] = {
    "active_user_decline": 0.22,
    "usage_decline": 0.14,
    "support_pressure": 0.14,
    "csat": 0.10,
    "nps": 0.12,
    "payment_delinquency": 0.12,
    "seat_utilization": 0.08,
    "feature_adoption_decline": 0.08,
}

# How the final score splits between "how many things are wrong" (the weighted
# average over components) and "how bad is the worst thing" (the single highest
# severity). A pure weighted average under-reacts to one severe signal: a 50%
# collapse in active users is a real escalation even when billing, CSAT and NPS
# all look fine, and a customer-success lead would act on it. A pure maximum
# over-reacts to one noisy metric. The split keeps multi-signal accounts ranked
# highest while letting a single severe signal reach MEDIUM on its own.
WEIGHTED_SHARE = 0.75
DOMINANT_SHARE = 0.25

# Urgency multipliers by days-to-renewal bucket.
RENEWAL_MULTIPLIERS: tuple[tuple[int, float], ...] = (
    (30, 1.18),
    (60, 1.10),
    (90, 1.04),
    (180, 1.00),
)
RENEWAL_MULTIPLIER_DEFAULT = 0.94


@dataclass(frozen=True)
class RiskSignal:
    """One deterministic, explainable contribution to the risk score."""

    key: str
    label: str
    value: float | None
    unit: str
    severity: float  # 0..1 concern level for this signal
    weight: float
    contribution: float  # points of the final 0..100 score
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RiskAssessment:
    customer_id: str
    score: float
    level: RiskLevel
    signals: list[RiskSignal]
    renewal_multiplier: float
    days_to_renewal: int | None
    coverage: float  # fraction of weight with usable data
    missing_signals: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "customer_id": self.customer_id,
            "score": self.score,
            "level": self.level.value,
            "renewal_multiplier": self.renewal_multiplier,
            "days_to_renewal": self.days_to_renewal,
            "coverage": self.coverage,
            "missing_signals": list(self.missing_signals),
            "signals": [signal.to_dict() for signal in self.signals],
        }

    @property
    def top_signals(self) -> list[RiskSignal]:
        return sorted(self.signals, key=lambda s: s.contribution, reverse=True)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _decline_severity(pct_change: float | None, *, full_concern_at: float) -> float | None:
    """Map a negative percentage change to 0..1 concern.

    ``full_concern_at`` is the drop (as a negative percentage) that counts as
    maximum concern, e.g. -50.0. Growth yields 0.0 rather than a negative value
    so a healthy signal cannot subsidise an unhealthy one.
    """
    if pct_change is None:
        return None
    if pct_change >= 0:
        return 0.0
    return _clamp(pct_change / full_concern_at)


def renewal_multiplier(days: int | None) -> float:
    if days is None:
        return 1.0
    if days < 0:
        # Renewal date already passed without an outcome: maximum urgency.
        return RENEWAL_MULTIPLIERS[0][1]
    for threshold, multiplier in RENEWAL_MULTIPLIERS:
        if days <= threshold:
            return multiplier
    return RENEWAL_MULTIPLIER_DEFAULT


def risk_level_for(score: float) -> RiskLevel:
    settings = get_settings()
    if score >= settings.risk_threshold_critical:
        return RiskLevel.CRITICAL
    if score >= settings.risk_threshold_high:
        return RiskLevel.HIGH
    if score >= settings.risk_threshold_medium:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def assess_risk(
    *,
    customer_id: str,
    usage: WindowedUsage,
    support: SupportSummary,
    payments: PaymentSummary,
    nps: NpsSummary,
    seats_purchased: int | None,
    renewal_date: date | None,
    as_of: date,
) -> RiskAssessment:
    """Compute the baseline risk score from deterministic inputs only."""
    severities: dict[str, tuple[float | None, float | None, str, str]] = {}

    # --- usage ------------------------------------------------------------
    dau_change = calculate_active_user_change(usage)
    severities["active_user_decline"] = (
        _decline_severity(dau_change, full_concern_at=-60.0),
        dau_change,
        "%",
        _usage_detail(usage, dau_change),
    )

    usage_change = calculate_usage_change(usage)
    severities["usage_decline"] = (
        _decline_severity(usage_change, full_concern_at=-60.0),
        usage_change,
        "%",
        f"Session/API volume changed {usage_change:+.1f}% versus the prior window."
        if usage_change is not None
        else "No comparable usage history.",
    )

    adoption_change = calculate_feature_adoption_change(usage)
    severities["feature_adoption_decline"] = (
        _decline_severity(adoption_change, full_concern_at=-40.0),
        adoption_change,
        "%",
        f"Feature adoption score changed {adoption_change:+.1f}%."
        if adoption_change is not None
        else "No feature-adoption history.",
    )

    utilization = calculate_seat_utilization(usage.latest_seats_active, seats_purchased)
    severities["seat_utilization"] = (
        None if utilization is None else _clamp((0.8 - utilization) / 0.8),
        None if utilization is None else round(utilization * 100, 2),
        "%",
        f"{usage.latest_seats_active} of {seats_purchased} purchased seats active."
        if utilization is not None
        else "Seat utilisation unavailable (no seat count or no usage rows).",
    )

    # --- support ----------------------------------------------------------
    growth = support.ticket_growth_pct
    if growth is None and support.recent_ticket_count == 0 and support.baseline_ticket_count == 0:
        support_severity: float | None = 0.0
        support_detail = "No support tickets in the observed period."
    elif growth is None:
        support_severity = None
        support_detail = "Insufficient ticket history to compare windows."
    else:
        volume_component = _clamp(growth / 150.0) if growth > 0 else 0.0
        unresolved_component = _clamp(support.unresolved_critical_count / 3.0)
        support_severity = _clamp(0.65 * volume_component + 0.35 * unresolved_component)
        support_detail = (
            f"Ticket volume changed {growth:+.1f}% with {support.unresolved_critical_count} "
            f"unresolved high/critical ticket(s)."
        )
    severities["support_pressure"] = (support_severity, growth, "%", support_detail)

    csat = support.average_csat
    severities["csat"] = (
        None if csat is None else _clamp((4.2 - csat) / 2.2),
        csat,
        "/5",
        f"Average CSAT {csat:.2f} across {support.csat_responses} rated ticket(s)."
        if csat is not None
        else "No CSAT responses recorded.",
    )

    # --- sentiment --------------------------------------------------------
    if nps.latest_score is None:
        nps_severity: float | None = None
        nps_detail = "No NPS response on record."
    else:
        level_component = _clamp((7.0 - nps.latest_score) / 7.0)
        drop_component = _clamp(-(nps.score_delta or 0) / 5.0) if nps.score_delta is not None else 0.0
        nps_severity = _clamp(0.7 * level_component + 0.3 * drop_component)
        delta_text = f" (changed {nps.score_delta:+d} from the previous response)" if nps.score_delta else ""
        nps_detail = f"Latest NPS {nps.latest_score}/10{delta_text}."
    nps_value = float(nps.latest_score) if nps.latest_score is not None else None
    severities["nps"] = (nps_severity, nps_value, "/10", nps_detail)

    # --- billing ----------------------------------------------------------
    if payments.invoice_count == 0:
        payment_severity: float | None = None
        payment_detail = "No invoices on record."
    else:
        overdue_component = _clamp(payments.max_days_overdue / 45.0)
        ratio_component = _clamp(payments.delinquency_ratio or 0.0)
        payment_severity = _clamp(0.7 * overdue_component + 0.3 * ratio_component)
        payment_detail = (
            f"{payments.overdue_invoice_count} of {payments.invoice_count} invoice(s) unpaid; "
            f"worst invoice {payments.max_days_overdue} day(s) overdue."
        )
    severities["payment_delinquency"] = (
        payment_severity,
        float(payments.max_days_overdue),
        "days",
        payment_detail,
    )

    # --- aggregate --------------------------------------------------------
    labels = {
        "active_user_decline": "Active user decline",
        "usage_decline": "Product usage decline",
        "support_pressure": "Support pressure",
        "csat": "Support satisfaction",
        "nps": "Relationship sentiment (NPS)",
        "payment_delinquency": "Billing delinquency",
        "seat_utilization": "Seat utilisation",
        "feature_adoption_decline": "Feature adoption decline",
    }

    usable_weight = sum(WEIGHTS[key] for key, (sev, *_rest) in severities.items() if sev is not None)
    missing = [key for key, (sev, *_rest) in severities.items() if sev is None]
    days = days_until_renewal(renewal_date, as_of=as_of)
    multiplier = renewal_multiplier(days)

    signals: list[RiskSignal] = []
    weighted = 0.0
    dominant = 0.0
    if usable_weight > 0:
        for key, (severity, value, unit, detail) in severities.items():
            if severity is None:
                continue
            weight = WEIGHTS[key]
            # Renormalise so missing data neither inflates nor deflates the score.
            effective_weight = weight / usable_weight
            contribution = severity * effective_weight * 100.0 * multiplier * WEIGHTED_SHARE
            weighted += severity * effective_weight
            dominant = max(dominant, severity)
            signals.append(
                RiskSignal(
                    key=key,
                    label=labels[key],
                    value=value,
                    unit=unit,
                    severity=round(severity, 4),
                    weight=round(effective_weight, 4),
                    contribution=round(contribution, 2),
                    detail=detail,
                )
            )

    raw_score = WEIGHTED_SHARE * weighted + DOMINANT_SHARE * dominant
    score = round(_clamp(raw_score * multiplier, 0.0, 1.0) * 100.0, 2)
    signals.sort(key=lambda signal: signal.contribution, reverse=True)

    return RiskAssessment(
        customer_id=customer_id,
        score=score,
        level=risk_level_for(score),
        signals=signals,
        renewal_multiplier=multiplier,
        days_to_renewal=days,
        coverage=round(usable_weight, 4),
        missing_signals=missing,
    )


def _usage_detail(usage: WindowedUsage, change: float | None) -> str:
    if change is None:
        if usage.recent_points == 0 and usage.baseline_points == 0:
            return "No usage history recorded."
        if usage.baseline_points == 0:
            return f"Only {usage.recent_points} recent usage data point(s); no baseline window to compare against."
        return "Insufficient usage history to compare windows."
    return (
        f"Average daily active users changed {change:+.1f}% "
        f"({usage.baseline_active_users:.1f} → {usage.recent_active_users:.1f})."
    )


def blend_scores(heuristic_score: float, agent_score: float | None, *, max_shift: float = 15.0) -> float:
    """Bound how far the LLM may move the deterministic score.

    The investigator sees qualitative evidence the heuristic cannot read (an
    email naming a competitor, a lost executive sponsor), so it is allowed to
    adjust the score — but only within ``max_shift`` points. This keeps rankings
    stable and auditable instead of letting a model hallucinate a 95.
    """
    if agent_score is None:
        return round(heuristic_score, 2)
    low = heuristic_score - max_shift
    high = heuristic_score + max_shift
    return round(_clamp(min(max(agent_score, low), high), 0.0, 100.0), 2)


def formula_documentation() -> dict[str, Any]:
    """Machine-readable description of the scoring model, surfaced in the API."""
    return {
        "model_type": "transparent_weighted_heuristic",
        "is_trained_model": False,
        "description": (
            "Weighted sum of eight deterministic customer-health components, renormalised over "
            "the components with available data and multiplied by a renewal-urgency factor. "
            "Not a trained or calibrated predictive model."
        ),
        "weights": dict(WEIGHTS),
        "aggregation": {
            "weighted_average_share": WEIGHTED_SHARE,
            "dominant_signal_share": DOMINANT_SHARE,
            "note": (
                "The score blends the weighted average of all available components with the single "
                "highest component severity, so one severe signal can raise an account on its own."
            ),
        },
        "renewal_multipliers": {
            "<=30d": 1.18,
            "<=60d": 1.10,
            "<=90d": 1.04,
            "<=180d": 1.00,
            ">180d": RENEWAL_MULTIPLIER_DEFAULT,
        },
        "levels": {
            "CRITICAL": f">= {get_settings().risk_threshold_critical}",
            "HIGH": f">= {get_settings().risk_threshold_high}",
            "MEDIUM": f">= {get_settings().risk_threshold_medium}",
            "LOW": f"< {get_settings().risk_threshold_medium}",
        },
        "agent_adjustment_band_points": 15.0,
    }
