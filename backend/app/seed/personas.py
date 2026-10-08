"""Customer personas.

A persona is a *correlated* scenario, not a bag of independent random numbers.
Each one specifies how usage, support, billing and sentiment move together, what
documents the account produces, and how likely that account was to actually
churn. That correlation is the whole point: an investigation is only meaningful
if there is a real story in the data to find, and an evaluation is only
meaningful if the label is not trivially predictable.

Deliberate difficulty:

* ``FALSE_POSITIVE_SUPPORT_SPIKE`` looks bad quantitatively and renews.
* ``QUIET_DISENGAGEMENT`` looks fine quantitatively and churns — the signal is
  only in the documents.
* ``HEALTHY_TEMPORARILY_INACTIVE`` has a usage dip with a benign explanation.
* Every persona has a churn *probability*, not a churn certainty, so the
  heuristic model cannot reach a perfect AUC.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Persona(StrEnum):
    USAGE_DECLINE = "USAGE_DECLINE"
    SUPPORT_FRUSTRATION = "SUPPORT_FRUSTRATION"
    PRICING_PRESSURE = "PRICING_PRESSURE"
    COMPETITOR_EVALUATION = "COMPETITOR_EVALUATION"
    POOR_ONBOARDING = "POOR_ONBOARDING"
    MISSING_FEATURE = "MISSING_FEATURE"
    SPONSOR_LOST = "SPONSOR_LOST"
    BILLING_PROBLEMS = "BILLING_PROBLEMS"
    HEALTHY_EXPANDING = "HEALTHY_EXPANDING"
    HEALTHY_TEMPORARILY_INACTIVE = "HEALTHY_TEMPORARILY_INACTIVE"
    FALSE_POSITIVE_SUPPORT_SPIKE = "FALSE_POSITIVE_SUPPORT_SPIKE"
    QUIET_DISENGAGEMENT = "QUIET_DISENGAGEMENT"


@dataclass(frozen=True)
class PersonaProfile:
    """How one persona's signals move.

    Multipliers apply to the account's baseline level over the recent window;
    ``1.0`` means unchanged. Probabilities are sampled per account.
    """

    persona: Persona
    weight: float  # share of the population
    churn_probability: float  # P(CHURNED | persona)
    downgrade_probability: float = 0.0
    expand_probability: float = 0.0

    # Usage trajectory
    active_user_multiplier: float = 1.0
    session_multiplier: float = 1.0
    api_call_multiplier: float = 1.0
    adoption_multiplier: float = 1.0
    seat_utilization: float = 0.72

    # Support
    ticket_rate_multiplier: float = 1.0
    critical_ticket_bias: float = 0.1
    unresolved_bias: float = 0.15
    csat_center: float = 4.1
    resolution_hours_center: float = 14.0

    # Sentiment
    nps_center: int = 8
    nps_drop: int = 0

    # Billing
    overdue_probability: float = 0.05
    max_days_overdue: int = 0

    # Narrative
    document_themes: tuple[str, ...] = ()
    churn_reasons: tuple[str, ...] = ("not_specified",)
    description: str = ""
    # Signals that look alarming but are explained away in the documents.
    misleading: bool = False
    tags: tuple[str, ...] = field(default_factory=tuple)


PERSONAS: dict[Persona, PersonaProfile] = {
    Persona.USAGE_DECLINE: PersonaProfile(
        persona=Persona.USAGE_DECLINE,
        weight=0.10,
        churn_probability=0.62,
        downgrade_probability=0.15,
        active_user_multiplier=0.45,
        session_multiplier=0.40,
        api_call_multiplier=0.55,
        adoption_multiplier=0.70,
        seat_utilization=0.34,
        ticket_rate_multiplier=0.8,
        csat_center=3.8,
        nps_center=5,
        nps_drop=3,
        document_themes=("usage_decline", "workflow_change", "renewal_question"),
        churn_reasons=("low_adoption", "consolidation", "no_longer_needed"),
        description="Daily active users and sessions fell sharply across the last 30 days.",
    ),
    Persona.SUPPORT_FRUSTRATION: PersonaProfile(
        persona=Persona.SUPPORT_FRUSTRATION,
        weight=0.09,
        churn_probability=0.55,
        downgrade_probability=0.10,
        active_user_multiplier=0.82,
        session_multiplier=0.85,
        adoption_multiplier=0.9,
        seat_utilization=0.63,
        ticket_rate_multiplier=3.4,
        critical_ticket_bias=0.55,
        unresolved_bias=0.5,
        csat_center=2.2,
        resolution_hours_center=58.0,
        nps_center=3,
        nps_drop=4,
        document_themes=("support_escalation", "sla_complaint", "renewal_question"),
        churn_reasons=("support_quality", "unresolved_issues", "reliability"),
        description="Ticket volume tripled with unresolved critical issues and low CSAT.",
    ),
    Persona.PRICING_PRESSURE: PersonaProfile(
        persona=Persona.PRICING_PRESSURE,
        weight=0.08,
        churn_probability=0.48,
        downgrade_probability=0.28,
        active_user_multiplier=0.9,
        session_multiplier=0.92,
        seat_utilization=0.58,
        ticket_rate_multiplier=1.1,
        csat_center=3.9,
        nps_center=6,
        nps_drop=2,
        overdue_probability=0.25,
        max_days_overdue=18,
        document_themes=("pricing_pressure", "budget_cut", "renewal_negotiation"),
        churn_reasons=("price", "budget_cut", "cost_consolidation"),
        description="Budget scrutiny and renewal price pushback with healthy-ish usage.",
    ),
    Persona.COMPETITOR_EVALUATION: PersonaProfile(
        persona=Persona.COMPETITOR_EVALUATION,
        weight=0.07,
        churn_probability=0.58,
        downgrade_probability=0.08,
        active_user_multiplier=0.72,
        session_multiplier=0.75,
        adoption_multiplier=0.85,
        seat_utilization=0.55,
        ticket_rate_multiplier=1.6,
        critical_ticket_bias=0.3,
        csat_center=3.4,
        nps_center=4,
        nps_drop=4,
        document_themes=("competitor_evaluation", "feature_gap", "renewal_negotiation"),
        churn_reasons=("competitor", "feature_gap", "price"),
        description="Actively evaluating alternative platforms ahead of renewal.",
        tags=("intent_signal",),
    ),
    Persona.POOR_ONBOARDING: PersonaProfile(
        persona=Persona.POOR_ONBOARDING,
        weight=0.07,
        churn_probability=0.52,
        active_user_multiplier=0.55,
        session_multiplier=0.5,
        adoption_multiplier=0.45,
        seat_utilization=0.28,
        ticket_rate_multiplier=1.8,
        unresolved_bias=0.3,
        csat_center=3.1,
        nps_center=5,
        nps_drop=1,
        document_themes=("onboarding_problems", "low_adoption", "training_request"),
        churn_reasons=("onboarding", "low_adoption", "internal_change"),
        description="Never reached activation: low seat utilisation and adoption since launch.",
    ),
    Persona.MISSING_FEATURE: PersonaProfile(
        persona=Persona.MISSING_FEATURE,
        weight=0.07,
        churn_probability=0.45,
        downgrade_probability=0.12,
        active_user_multiplier=0.85,
        session_multiplier=0.88,
        adoption_multiplier=0.78,
        seat_utilization=0.66,
        ticket_rate_multiplier=2.0,
        critical_ticket_bias=0.25,
        csat_center=3.5,
        nps_center=5,
        nps_drop=2,
        document_themes=("feature_gap", "roadmap_request", "competitor_evaluation"),
        churn_reasons=("feature_gap", "competitor", "unmet_requirements"),
        description="Blocked on a specific capability gap raised repeatedly.",
    ),
    Persona.SPONSOR_LOST: PersonaProfile(
        persona=Persona.SPONSOR_LOST,
        weight=0.06,
        churn_probability=0.56,
        downgrade_probability=0.14,
        active_user_multiplier=0.68,
        session_multiplier=0.7,
        adoption_multiplier=0.8,
        seat_utilization=0.48,
        ticket_rate_multiplier=0.7,
        csat_center=3.9,
        nps_center=6,
        document_themes=("sponsor_change", "reorg", "renewal_question"),
        churn_reasons=("champion_left", "reorg", "strategy_change"),
        description="Executive sponsor left; no identified replacement owner.",
    ),
    Persona.BILLING_PROBLEMS: PersonaProfile(
        persona=Persona.BILLING_PROBLEMS,
        weight=0.06,
        churn_probability=0.42,
        downgrade_probability=0.18,
        active_user_multiplier=0.95,
        session_multiplier=0.95,
        seat_utilization=0.7,
        ticket_rate_multiplier=1.3,
        csat_center=3.8,
        nps_center=7,
        overdue_probability=0.95,
        max_days_overdue=52,
        document_themes=("billing_dispute", "procurement_delay"),
        churn_reasons=("billing", "procurement", "payment_failure"),
        description="Materially overdue invoices and procurement friction.",
    ),
    Persona.HEALTHY_EXPANDING: PersonaProfile(
        persona=Persona.HEALTHY_EXPANDING,
        weight=0.17,
        churn_probability=0.03,
        expand_probability=0.45,
        active_user_multiplier=1.28,
        session_multiplier=1.32,
        api_call_multiplier=1.4,
        adoption_multiplier=1.2,
        seat_utilization=0.92,
        ticket_rate_multiplier=1.0,
        csat_center=4.6,
        nps_center=9,
        overdue_probability=0.02,
        document_themes=("expansion", "success_story", "qbr_positive"),
        churn_reasons=("not_specified",),
        description="Growing usage, high satisfaction, expansion conversations underway.",
    ),
    Persona.HEALTHY_TEMPORARILY_INACTIVE: PersonaProfile(
        persona=Persona.HEALTHY_TEMPORARILY_INACTIVE,
        weight=0.08,
        churn_probability=0.09,
        active_user_multiplier=0.58,
        session_multiplier=0.55,
        adoption_multiplier=0.95,
        seat_utilization=0.45,
        ticket_rate_multiplier=0.6,
        csat_center=4.4,
        nps_center=9,
        document_themes=("seasonal_pause", "planned_inactivity", "qbr_positive"),
        churn_reasons=("not_specified",),
        description="Usage dipped for a known seasonal or project reason; relationship is strong.",
        misleading=True,
    ),
    Persona.FALSE_POSITIVE_SUPPORT_SPIKE: PersonaProfile(
        persona=Persona.FALSE_POSITIVE_SUPPORT_SPIKE,
        weight=0.08,
        churn_probability=0.11,
        expand_probability=0.2,
        active_user_multiplier=1.08,
        session_multiplier=1.05,
        adoption_multiplier=1.05,
        seat_utilization=0.85,
        ticket_rate_multiplier=3.8,
        critical_ticket_bias=0.2,
        unresolved_bias=0.05,
        csat_center=4.5,
        resolution_hours_center=5.0,
        nps_center=9,
        document_themes=("migration_project", "support_volume_explained", "qbr_positive"),
        churn_reasons=("not_specified",),
        description="Ticket spike driven by a large rollout, resolved fast with high CSAT.",
        misleading=True,
    ),
    Persona.QUIET_DISENGAGEMENT: PersonaProfile(
        persona=Persona.QUIET_DISENGAGEMENT,
        weight=0.07,
        churn_probability=0.5,
        downgrade_probability=0.2,
        active_user_multiplier=0.93,
        session_multiplier=0.95,
        adoption_multiplier=0.92,
        seat_utilization=0.68,
        ticket_rate_multiplier=0.35,
        csat_center=4.2,
        nps_center=7,
        document_themes=("silent_stakeholders", "missed_qbr", "internal_review"),
        churn_reasons=("disengagement", "strategy_change", "consolidation"),
        description=(
            "Metrics look acceptable; the risk only appears in notes — missed QBRs, "
            "unreturned outreach, an internal review underway."
        ),
        misleading=True,
        tags=("qualitative_only",),
    ),
}


def persona_weights() -> list[tuple[Persona, float]]:
    return [(persona, profile.weight) for persona, profile in PERSONAS.items()]


def validate_weights() -> float:
    total = sum(profile.weight for profile in PERSONAS.values())
    return round(total, 6)
