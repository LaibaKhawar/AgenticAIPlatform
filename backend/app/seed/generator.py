"""Synthetic dataset generator.

Deterministic: a given ``SEED_RANDOM_SEED`` always produces the same database,
down to the document text, so evaluation numbers are comparable across runs and
a demo is reproducible.

Scale and shape (defaults, ~3,000 customers):

* ~450 ``CHURNED``, ~2,200 ``RENEWED``, the remainder ``DOWNGRADED``/``EXPANDED``
  or ``UNKNOWN`` for accounts whose renewal is still ahead of them;
* several hundred with a renewal inside the next 90 days;
* 12 correlated personas, each with its own usage/support/billing/sentiment
  trajectory and document set;
* noise on every signal and probabilistic outcomes, so churn is *not* perfectly
  predictable from the features.

Performance: rows are built in memory per batch and written with bulk inserts;
embeddings are generated with the local deterministic embedder. No LLM calls.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from app.core.clock import today as clock_today
from app.core.config import get_settings
from app.core.logging import get_logger
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
from app.models.enums import (
    AccountTier,
    CustomerOutcome,
    PaymentStatus,
    SubscriptionStatus,
    TicketPriority,
    TicketStatus,
)
from app.rag.chunking import chunk_text
from app.seed.documents import build_documents
from app.seed.personas import PERSONAS, Persona

logger = get_logger(__name__)

DEMO_EXTERNAL_ID = "CUST-000001"
DEMO_COMPANY = "Acme Corp"

INDUSTRIES = (
    "Software",
    "Financial Services",
    "Healthcare",
    "Manufacturing",
    "Retail",
    "Logistics",
    "Education",
    "Telecommunications",
    "Energy",
    "Professional Services",
    "Media",
    "Insurance",
)
COUNTRIES = (
    "United States",
    "United Kingdom",
    "Germany",
    "Canada",
    "Australia",
    "Netherlands",
    "France",
    "Sweden",
    "Singapore",
    "Ireland",
    "Spain",
    "Japan",
)
COMPANY_PREFIXES = (
    "Northwind",
    "Orbital",
    "Brightline",
    "Harbor",
    "Lumen",
    "Vertex",
    "Cascade",
    "Ironwood",
    "Blue Ridge",
    "Meridian",
    "Copperleaf",
    "Silverpine",
    "Atlas",
    "Keystone",
    "Clearwater",
    "Summit",
    "Beacon",
    "Granite",
    "Juniper",
    "Mapleton",
    "Redwood",
    "Stonebridge",
    "Thornhill",
    "Westfield",
    "Larkspur",
    "Foxglove",
    "Halcyon",
    "Kestrel",
    "Lantern",
    "Marigold",
)
COMPANY_SUFFIXES = (
    "Health",
    "Labs",
    "Systems",
    "Studio",
    "Group",
    "Analytics",
    "Partners",
    "Logistics",
    "Digital",
    "Industries",
    "Technologies",
    "Networks",
    "Capital",
    "Collective",
    "Works",
)

TIER_CONFIG: dict[AccountTier, dict[str, Any]] = {
    AccountTier.ENTERPRISE: {
        "weight": 0.18,
        "mrr": (6000, 24000),
        "seats": (120, 900),
        "employees": (1200, 40000),
        "size": "1000+",
        "plans": ("Enterprise", "Enterprise Plus"),
    },
    AccountTier.MID_MARKET: {
        "weight": 0.34,
        "mrr": (1800, 6500),
        "seats": (40, 180),
        "employees": (250, 1500),
        "size": "250-1000",
        "plans": ("Growth", "Scale"),
    },
    AccountTier.SMB: {
        "weight": 0.34,
        "mrr": (400, 1800),
        "seats": (8, 45),
        "employees": (25, 250),
        "size": "25-250",
        "plans": ("Starter", "Team"),
    },
    AccountTier.STARTUP: {
        "weight": 0.14,
        "mrr": (120, 700),
        "seats": (3, 20),
        "employees": (5, 60),
        "size": "1-25",
        "plans": ("Starter",),
    },
}

TICKET_CATEGORIES = (
    "Reporting",
    "Integrations",
    "Performance",
    "Billing",
    "Authentication",
    "Data import",
    "Permissions",
    "API",
    "How-to",
    "Bug",
)
ACCOUNT_MANAGERS = (
    "Avery Chen",
    "Maya Patel",
    "Jordan Lee",
    "Sam Rivera",
    "Taylor Brooks",
    "Noor Haddad",
    "Chris Okafor",
    "Lena Nowak",
    "Diego Silva",
    "Ruth Mensah",
)

# Usage is sampled weekly over this horizon rather than daily: 26 points per
# customer keeps the dataset informative while bounding row count (~78k rows at
# 3,000 customers instead of ~550k).
USAGE_WEEKS = 26
USAGE_INTERVAL_DAYS = 7


@dataclass
class SeedStats:
    customers: int = 0
    subscriptions: int = 0
    usage_rows: int = 0
    tickets: int = 0
    payments: int = 0
    nps: int = 0
    documents: int = 0
    chunks: int = 0
    outcomes: dict[str, int] = field(default_factory=dict)
    personas: dict[str, int] = field(default_factory=dict)
    renewing_90_days: int = 0
    injection_documents: int = 0
    duration_seconds: float = 0.0
    skipped_existing: bool = False

    def as_dict(self) -> dict[str, Any]:
        if self.skipped_existing:
            return {
                "skipped": True,
                "reason": "the database already contains customer data",
                "existing_customers": self.customers,
                "hint": "pass --reset to regenerate the dataset",
            }
        return {
            "customers": self.customers,
            "subscriptions": self.subscriptions,
            "usage_rows": self.usage_rows,
            "tickets": self.tickets,
            "payments": self.payments,
            "nps_responses": self.nps,
            "documents": self.documents,
            "document_chunks": self.chunks,
            "outcomes": self.outcomes,
            "personas": self.personas,
            "renewing_within_90_days": self.renewing_90_days,
            "documents_with_injection_attempt": self.injection_documents,
            "duration_seconds": round(self.duration_seconds, 2),
        }


# Target class balance for the generated dataset, as a share of the population.
# Chosen to match a plausible enterprise portfolio: most accounts renew, a
# meaningful minority churn, and a few hundred are still live with the renewal
# ahead of them (those are what an investigation run actually operates on).
OUTCOME_MIX: dict[CustomerOutcome, float] = {
    CustomerOutcome.CHURNED: 0.150,
    CustomerOutcome.RENEWED: 0.716,
    CustomerOutcome.DOWNGRADED: 0.017,
    CustomerOutcome.EXPANDED: 0.017,
    CustomerOutcome.UNKNOWN: 0.100,
}


def _weighted_choice(rng: random.Random, options: list[tuple[Any, float]]) -> Any:
    total = sum(weight for _option, weight in options)
    roll = rng.uniform(0, total)
    upto = 0.0
    for option, weight in options:
        upto += weight
        if roll <= upto:
            return option
    return options[-1][0]


def _build_outcome_plan(rng: random.Random, count: int) -> list[CustomerOutcome]:
    """Exact outcome counts for ``count`` customers, shuffled deterministically.

    Assigning outcomes up front (rather than sampling per customer) means the
    dataset always has the documented class balance, which the evaluation
    harness depends on for stable base rates.
    """
    plan: list[CustomerOutcome] = []
    for outcome, share in OUTCOME_MIX.items():
        plan.extend([outcome] * round(count * share))
    # Rounding drift lands on RENEWED, the majority class.
    while len(plan) < count:
        plan.append(CustomerOutcome.RENEWED)
    del plan[count:]
    rng.shuffle(plan)
    return plan


def _persona_posterior(outcome: CustomerOutcome) -> list[tuple[Persona, float]]:
    """P(persona | outcome) ∝ P(persona) · P(outcome | persona).

    This is what preserves the correlation: a churned account is much more
    likely to be a ``SUPPORT_FRUSTRATION`` story than a ``HEALTHY_EXPANDING``
    one — but not impossibly so, which is exactly the ambiguity an investigator
    has to reason through.
    """
    weights: list[tuple[Persona, float]] = []
    for persona, profile in PERSONAS.items():
        if outcome is CustomerOutcome.CHURNED:
            likelihood = profile.churn_probability
        elif outcome is CustomerOutcome.DOWNGRADED:
            likelihood = profile.downgrade_probability or 0.02
        elif outcome is CustomerOutcome.EXPANDED:
            likelihood = profile.expand_probability or 0.02
        elif outcome is CustomerOutcome.RENEWED:
            likelihood = max(
                0.01,
                1.0
                - profile.churn_probability
                - profile.downgrade_probability
                - profile.expand_probability,
            )
        else:  # UNKNOWN — a live account can be in any state
            likelihood = 1.0
        if likelihood > 0:
            weights.append((persona, profile.weight * likelihood))
    return weights


def _sample_persona_for_outcome(rng: random.Random, outcome: CustomerOutcome) -> Persona:
    return _weighted_choice(rng, _persona_posterior(outcome))


# How severely the persona's story actually played out, by outcome. A persona is
# a *narrative* ("support frustration"); the outcome sets its *intensity*. Two
# accounts can both be support-frustration stories, but the one that renewed was
# the one whose tickets got resolved and whose CSAT recovered — so its signals
# must be milder than the one that churned. Without this, the dataset says a
# CSAT of 2.2 and tripled ticket volume is only 29% predictive of churn, which
# is not true of real portfolios and unfairly handicaps any screening model.
OUTCOME_SEVERITY: dict[CustomerOutcome, float] = {
    CustomerOutcome.CHURNED: 1.00,
    CustomerOutcome.DOWNGRADED: 0.80,
    CustomerOutcome.RENEWED: 0.38,
    CustomerOutcome.EXPANDED: 0.12,
    # Live accounts: the story is still unresolved, so signals run hot.
    CustomerOutcome.UNKNOWN: 0.85,
}

# Spread on the severity factor. This is what keeps churn genuinely uncertain:
# the distributions overlap, so a high score is evidence rather than proof.
SEVERITY_JITTER = 0.26


@dataclass
class SignalIntensity:
    """Outcome-conditioned scaling applied to a persona's signal deviations."""

    factor: float

    def scale(self, multiplier: float) -> float:
        """Shrink a multiplier's deviation from 1.0 towards neutral."""
        return 1.0 + (multiplier - 1.0) * self.factor

    def toward(self, value: float, healthy: float) -> float:
        """Interpolate an absolute level (CSAT, NPS) back towards healthy."""
        return healthy + (value - healthy) * self.factor

    def probability(self, value: float) -> float:
        return max(0.0, min(1.0, value * self.factor))


def _signal_intensity(rng: random.Random, outcome: CustomerOutcome) -> SignalIntensity:
    base = OUTCOME_SEVERITY[outcome]
    factor = base + rng.uniform(-SEVERITY_JITTER, SEVERITY_JITTER)
    return SignalIntensity(factor=max(0.0, min(1.35, factor)))


@dataclass
class EffectiveProfile:
    """A persona profile with its deviations scaled by outcome severity.

    Mirrors the attribute names of :class:`~app.seed.personas.PersonaProfile` so
    the row generators are unchanged.
    """

    active_user_multiplier: float
    session_multiplier: float
    api_call_multiplier: float
    adoption_multiplier: float
    seat_utilization: float
    ticket_rate_multiplier: float
    critical_ticket_bias: float
    unresolved_bias: float
    csat_center: float
    resolution_hours_center: float
    nps_center: int
    nps_drop: int
    overdue_probability: float
    max_days_overdue: int


def _effective_profile(profile: Any, intensity: SignalIntensity) -> EffectiveProfile:
    return EffectiveProfile(
        active_user_multiplier=intensity.scale(profile.active_user_multiplier),
        session_multiplier=intensity.scale(profile.session_multiplier),
        api_call_multiplier=intensity.scale(profile.api_call_multiplier),
        adoption_multiplier=intensity.scale(profile.adoption_multiplier),
        seat_utilization=max(0.05, min(1.0, intensity.toward(profile.seat_utilization, 0.80))),
        ticket_rate_multiplier=max(0.1, intensity.scale(profile.ticket_rate_multiplier)),
        critical_ticket_bias=intensity.probability(profile.critical_ticket_bias) + 0.03,
        unresolved_bias=intensity.probability(profile.unresolved_bias) + 0.04,
        csat_center=max(1.0, min(5.0, intensity.toward(profile.csat_center, 4.4))),
        resolution_hours_center=max(1.0, intensity.toward(profile.resolution_hours_center, 10.0)),
        nps_center=round(max(0.0, min(10.0, intensity.toward(profile.nps_center, 9.0)))),
        nps_drop=round(max(0.0, profile.nps_drop * intensity.factor)),
        overdue_probability=intensity.probability(profile.overdue_probability),
        max_days_overdue=round(profile.max_days_overdue * intensity.factor),
    )


def _jitter(rng: random.Random, value: float, spread: float = 0.15) -> float:
    """Multiplicative noise so signals are never textbook-clean."""
    return value * rng.uniform(1 - spread, 1 + spread)


def _company_name(rng: random.Random, index: int) -> str:
    prefix = COMPANY_PREFIXES[index % len(COMPANY_PREFIXES)]
    suffix = COMPANY_SUFFIXES[(index // len(COMPANY_PREFIXES)) % len(COMPANY_SUFFIXES)]
    serial = index // (len(COMPANY_PREFIXES) * len(COMPANY_SUFFIXES))
    name = f"{prefix} {suffix}"
    return f"{name} {serial + 1}" if serial else name


# --------------------------------------------------------------------------- #
# Per-customer generation
# --------------------------------------------------------------------------- #


@dataclass
class GeneratedCustomer:
    customer: dict[str, Any]
    subscription: dict[str, Any]
    usage: list[dict[str, Any]]
    tickets: list[dict[str, Any]]
    payments: list[dict[str, Any]]
    nps: list[dict[str, Any]]
    documents: list[tuple[dict[str, Any], list[dict[str, Any]]]]
    outcome: dict[str, Any]
    persona: Persona
    renewal_date: date
    has_injection: bool


def _generate_customer(
    *,
    rng: random.Random,
    index: int,
    as_of: date,
    outcome: CustomerOutcome,
    persona: Persona | None = None,
    force_tier: AccountTier | None = None,
) -> GeneratedCustomer:
    """Generate one customer whose signals are consistent with ``outcome``.

    The outcome is assigned by the stratified plan (see
    :func:`_build_outcome_plan`) rather than sampled here, so the dataset hits
    its target class balance exactly. The persona — which determines *how* the
    signals move — is sampled conditioned on that outcome, which is what keeps
    the correlation realistic without making churn deterministic.
    """
    customer_id = uuid.uuid4()
    chosen_persona = persona or _sample_persona_for_outcome(rng, outcome)
    narrative = PERSONAS[chosen_persona]
    intensity = _signal_intensity(rng, outcome)
    profile = _effective_profile(narrative, intensity)

    tier = force_tier or _weighted_choice(rng, [(tier, config["weight"]) for tier, config in TIER_CONFIG.items()])
    config = TIER_CONFIG[tier]

    company = _company_name(rng, index)
    external_id = f"CUST-{index + 1:06d}"

    # --- timeline ---------------------------------------------------------
    is_historical = outcome is not CustomerOutcome.UNKNOWN
    if is_historical:
        # Resolved accounts renewed or churned at some point in the past year.
        renewal_date = as_of - timedelta(days=rng.randint(5, 330))
    else:
        # Live accounts: weighted towards the next few months so the
        # candidate-selection stage always has something real to work with.
        horizon = rng.choice([45, 45, 90, 90, 90, 180, 330])
        renewal_date = as_of + timedelta(days=rng.randint(1, horizon))

    # Signals are generated relative to the decision point, not to today, so
    # evaluating "as of the outcome date" sees pre-outcome behaviour.
    reference_date = renewal_date if is_historical else as_of

    mrr = round(_jitter(rng, rng.uniform(*config["mrr"]), 0.1), 2)
    seats = int(_jitter(rng, rng.uniform(*config["seats"]), 0.12))
    acv = round(mrr * 12, 2)
    contract_start = renewal_date - timedelta(days=365)
    subscription_status = (
        SubscriptionStatus.CANCELLED
        if outcome is CustomerOutcome.CHURNED
        else (
            SubscriptionStatus.PAST_DUE
            if profile.overdue_probability > 0.8 and rng.random() < 0.6
            else SubscriptionStatus.ACTIVE
        )
    )

    customer_row = {
        "id": customer_id,
        "external_id": external_id,
        "company_name": company,
        "industry": rng.choice(INDUSTRIES),
        "country": rng.choice(COUNTRIES),
        "company_size": config["size"],
        "employee_count": int(rng.uniform(*config["employees"])),
        "account_tier": tier.value,
        "account_manager": rng.choice(ACCOUNT_MANAGERS),
        "scenario_persona": chosen_persona.value,
    }

    subscription_row = {
        "id": uuid.uuid4(),
        "customer_id": customer_id,
        "plan": rng.choice(config["plans"]),
        "monthly_recurring_revenue": mrr,
        "annual_contract_value": acv,
        "contract_start": contract_start,
        "contract_end": renewal_date,
        "renewal_date": renewal_date,
        "subscription_status": subscription_status.value,
        "seats_purchased": seats,
    }

    usage_rows = _generate_usage(
        rng=rng, customer_id=customer_id, profile=profile, seats=seats, reference_date=reference_date
    )
    ticket_rows = _generate_tickets(
        rng=rng,
        customer_id=customer_id,
        profile=profile,
        tier=tier,
        reference_date=reference_date,
        external_id=external_id,
    )
    payment_rows = _generate_payments(
        rng=rng, customer_id=customer_id, profile=profile, mrr=mrr, reference_date=reference_date
    )
    nps_rows = _generate_nps(rng=rng, customer_id=customer_id, profile=profile, reference_date=reference_date)

    # ~1.5% of accounts carry a document with an embedded injection attempt.
    has_injection = rng.random() < 0.015
    # Mixed evidence: healthy accounts carry the occasional complaint, and an
    # account whose story resolved well carries a positive note alongside the
    # risk themes. Both exist so an investigator has to weigh conflicting
    # signals rather than pattern-match one document.
    cross_signal = None
    if intensity.factor < 0.45 and narrative.churn_probability > 0.4 and rng.random() < 0.55:
        cross_signal = "risky_with_positive"
    elif narrative.churn_probability < 0.2 and rng.random() < 0.3:
        cross_signal = "healthy_with_negative"

    document_rows = _generate_documents(
        rng=rng,
        customer_id=customer_id,
        company=company,
        persona=chosen_persona,
        themes=narrative.document_themes,
        renewal_date=renewal_date,
        as_of=reference_date,
        include_injection=has_injection,
        cross_signal=cross_signal,
    )

    outcome_row = {
        "id": uuid.uuid4(),
        "customer_id": customer_id,
        "outcome": outcome.value,
        "outcome_date": renewal_date if is_historical else None,
        "churn_reason": (
            rng.choice(narrative.churn_reasons)
            if outcome in {CustomerOutcome.CHURNED, CustomerOutcome.DOWNGRADED}
            else None
        ),
        "notes": narrative.description,
    }

    return GeneratedCustomer(
        customer=customer_row,
        subscription=subscription_row,
        usage=usage_rows,
        tickets=ticket_rows,
        payments=payment_rows,
        nps=nps_rows,
        documents=document_rows,
        outcome=outcome_row,
        persona=chosen_persona,
        renewal_date=renewal_date,
        has_injection=has_injection,
    )


def _generate_usage(
    *, rng: random.Random, customer_id: uuid.UUID, profile: Any, seats: int, reference_date: date
) -> list[dict[str, Any]]:
    """Weekly usage with a baseline period and a persona-shaped recent period."""
    baseline_active = max(2, int(seats * _jitter(rng, 0.78, 0.2)))
    baseline_sessions_per_user = _jitter(rng, rng.uniform(2.5, 6.0), 0.15)
    baseline_api = _jitter(rng, baseline_active * rng.uniform(30, 160), 0.2)
    baseline_adoption = _jitter(rng, rng.uniform(45, 85), 0.1)

    rows: list[dict[str, Any]] = []
    for week in range(USAGE_WEEKS):
        offset_days = (USAGE_WEEKS - 1 - week) * USAGE_INTERVAL_DAYS
        usage_date = reference_date - timedelta(days=offset_days)
        # The persona's trajectory ramps in over the final ~5 weeks.
        recent_weight = max(0.0, (week - (USAGE_WEEKS - 5)) / 5.0)

        def blend(baseline: float, multiplier: float, weight: float = recent_weight) -> float:
            return baseline * (1 - weight) + baseline * multiplier * weight

        active = max(0, int(_jitter(rng, blend(baseline_active, profile.active_user_multiplier), 0.12)))
        sessions = max(
            0,
            int(
                _jitter(
                    rng,
                    blend(baseline_active * baseline_sessions_per_user, profile.session_multiplier),
                    0.15,
                )
            ),
        )
        api_calls = max(0, int(_jitter(rng, blend(baseline_api, profile.api_call_multiplier), 0.2)))
        adoption = max(
            0.0,
            min(100.0, _jitter(rng, blend(baseline_adoption, profile.adoption_multiplier), 0.08)),
        )
        seats_active = max(
            0,
            min(
                seats,
                int(
                    _jitter(
                        rng,
                        seats * (profile.seat_utilization * recent_weight + 0.78 * (1 - recent_weight)),
                        0.1,
                    )
                ),
            ),
        )
        rows.append(
            {
                "id": uuid.uuid4(),
                "customer_id": customer_id,
                "usage_date": usage_date,
                "active_users": active,
                "total_logins": int(sessions * _jitter(rng, 1.4, 0.1)),
                "sessions": sessions,
                "projects_created": max(0, int(_jitter(rng, active * 0.12, 0.4))),
                "api_calls": api_calls,
                "feature_adoption_score": round(adoption, 2),
                "seats_active": seats_active,
            }
        )
    return rows


def _generate_tickets(
    *,
    rng: random.Random,
    customer_id: uuid.UUID,
    profile: Any,
    tier: AccountTier,
    reference_date: date,
    external_id: str,
) -> list[dict[str, Any]]:
    tier_base = {
        AccountTier.ENTERPRISE: 5.0,
        AccountTier.MID_MARKET: 3.0,
        AccountTier.SMB: 1.6,
        AccountTier.STARTUP: 0.9,
    }[tier]

    rows: list[dict[str, Any]] = []
    counter = 0
    # 90-day window split into a 60-day baseline and a 30-day recent period.
    for window_start, window_days, multiplier in (
        (90, 60, 1.0),
        (30, 30, profile.ticket_rate_multiplier),
    ):
        expected = tier_base * (window_days / 30.0) * multiplier
        count = max(0, int(rng.gauss(expected, max(0.6, expected * 0.3))))
        for _ in range(count):
            counter += 1
            created_offset = rng.randint(window_start - window_days, window_start)
            created = datetime.combine(
                reference_date - timedelta(days=created_offset),
                datetime.min.time(),
                tzinfo=UTC,
            ) + timedelta(hours=rng.randint(7, 19), minutes=rng.randint(0, 59))

            is_critical = rng.random() < profile.critical_ticket_bias
            priority = (
                rng.choice([TicketPriority.HIGH, TicketPriority.CRITICAL])
                if is_critical
                else rng.choice([TicketPriority.LOW, TicketPriority.NORMAL, TicketPriority.NORMAL])
            )
            unresolved = rng.random() < profile.unresolved_bias
            if unresolved:
                ticket_status = rng.choice([TicketStatus.OPEN, TicketStatus.PENDING, TicketStatus.ESCALATED])
                resolved_at = None
                resolution_hours = None
            else:
                ticket_status = rng.choice([TicketStatus.RESOLVED, TicketStatus.CLOSED])
                resolution_hours = round(
                    max(0.5, rng.gauss(profile.resolution_hours_center, profile.resolution_hours_center * 0.4)),
                    2,
                )
                resolved_at = created + timedelta(hours=resolution_hours)

            # Only some tickets get a CSAT response, as in real life.
            csat = None
            if resolved_at is not None and rng.random() < 0.55:
                csat = max(1.0, min(5.0, round(rng.gauss(profile.csat_center, 0.8) * 2) / 2))

            category = rng.choice(TICKET_CATEGORIES)
            rows.append(
                {
                    "id": uuid.uuid4(),
                    "customer_id": customer_id,
                    "external_ticket_id": f"TKT-{external_id[-6:]}-{counter:03d}",
                    "created_at": created,
                    "resolved_at": resolved_at,
                    "category": category,
                    "priority": priority.value,
                    "status": ticket_status.value,
                    "resolution_hours": resolution_hours,
                    "csat_score": csat,
                    "subject": _ticket_subject(rng, category, priority),
                    "description": _ticket_description(rng, category, priority, unresolved),
                }
            )
    return rows


def _ticket_subject(rng: random.Random, category: str, priority: TicketPriority) -> str:
    templates = {
        "Reporting": ("Scheduled report did not deliver", "Report totals do not reconcile"),
        "Integrations": ("Sync stopped overnight", "Connector authentication expired"),
        "Performance": ("Dashboard load times degraded", "Export times out on large datasets"),
        "Billing": ("Invoice does not match PO", "Need a copy of the latest invoice"),
        "Authentication": ("SSO login loop for new users", "MFA reset request"),
        "Data import": ("Import rejected without an error message", "Column mapping question"),
        "Permissions": ("User cannot see their own workspace", "Role change request"),
        "API": ("Rate limit hit during nightly job", "Pagination returns duplicates"),
        "How-to": ("How do we filter by cohort?", "Best practice for shared views"),
        "Bug": ("Chart renders empty after filter change", "Saved view reverts on reload"),
    }
    subject = rng.choice(templates.get(category, ("Support request",)))
    if priority in {TicketPriority.HIGH, TicketPriority.CRITICAL}:
        return f"[{priority.value}] {subject}"
    return subject


def _ticket_description(rng: random.Random, category: str, priority: TicketPriority, unresolved: bool) -> str:
    impact = (
        "This is blocking a business process and has been raised internally."
        if priority in {TicketPriority.HIGH, TicketPriority.CRITICAL}
        else "Not urgent, but we would like to understand the behaviour."
    )
    state = "Still waiting on a resolution." if unresolved else "Resolved after the workaround was applied."
    return f"{category} issue reported by the customer's team. {impact} {state}"


def _generate_payments(
    *, rng: random.Random, customer_id: uuid.UUID, profile: Any, mrr: float, reference_date: date
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for month in range(6, 0, -1):
        invoice_date = reference_date - timedelta(days=month * 30)
        # A small share of invoices legitimately have no due date (edge case the
        # analytics layer must tolerate).
        due_date = None if rng.random() < 0.03 else invoice_date + timedelta(days=30)
        is_recent = month <= 2
        overdue = is_recent and rng.random() < profile.overdue_probability

        if overdue:
            days_overdue = max(1, int(_jitter(rng, profile.max_days_overdue or rng.randint(5, 30), 0.3)))
            payment_status = PaymentStatus.FAILED if rng.random() < 0.2 else PaymentStatus.OVERDUE
            payment_date = None
        elif rng.random() < 0.05:
            days_overdue = 0
            payment_status = PaymentStatus.PENDING
            payment_date = None
        else:
            days_overdue = 0
            payment_status = PaymentStatus.PAID
            payment_date = invoice_date + timedelta(days=rng.randint(3, 34))

        rows.append(
            {
                "id": uuid.uuid4(),
                "customer_id": customer_id,
                "invoice_date": invoice_date,
                "due_date": due_date,
                "amount": round(mrr, 2),
                "payment_date": payment_date,
                "payment_status": payment_status.value,
                "days_overdue": days_overdue,
            }
        )
    return rows


def _generate_nps(
    *, rng: random.Random, customer_id: uuid.UUID, profile: Any, reference_date: date
) -> list[dict[str, Any]]:
    # ~12% of accounts never respond to a survey.
    if rng.random() < 0.12:
        return []

    rows: list[dict[str, Any]] = []
    responses = rng.randint(1, 3)
    earlier_score = max(0, min(10, int(rng.gauss(profile.nps_center + profile.nps_drop, 1.1))))
    for index in range(responses):
        is_latest = index == responses - 1
        score = max(0, min(10, int(rng.gauss(profile.nps_center, 1.2)))) if is_latest else earlier_score
        response_date = reference_date - timedelta(days=(responses - index) * rng.randint(70, 110))
        rows.append(
            {
                "id": uuid.uuid4(),
                "customer_id": customer_id,
                "response_date": response_date,
                "score": score,
                "feedback": _nps_feedback(rng, score),
            }
        )
    return rows


def _nps_feedback(rng: random.Random, score: int) -> str:
    if score >= 9:
        return rng.choice(
            (
                "The platform is central to how our team works. Support has been excellent.",
                "Reliable and easy to roll out to new teams. We recommend it internally.",
            )
        )
    if score >= 7:
        return rng.choice(
            (
                "Solid product. Reporting flexibility is the main thing we would improve.",
                "Works well for our core use case; onboarding new users takes effort.",
            )
        )
    if score >= 4:
        return rng.choice(
            (
                "It does the job but we have had support delays and some reporting gaps.",
                "Mixed. The core is good, the edges cost us time every month.",
            )
        )
    return rng.choice(
        (
            "Response times on open issues have been poor and it is affecting trust.",
            "We are reassessing whether this is the right tool for us next year.",
            "Too expensive for what we currently get out of it.",
        )
    )


def _generate_documents(
    *,
    rng: random.Random,
    customer_id: uuid.UUID,
    company: str,
    persona: Persona,
    themes: tuple[str, ...],
    renewal_date: date,
    as_of: date,
    include_injection: bool,
    cross_signal: str | None,
) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    drafts = build_documents(
        rng=rng,
        company=company,
        persona=persona,
        themes=themes,
        renewal_date=renewal_date,
        as_of=as_of,
        include_injection=include_injection,
        cross_signal=cross_signal,
    )
    results: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    for draft in drafts:
        document_id = uuid.uuid4()
        document_row = {
            "id": document_id,
            "customer_id": customer_id,
            "source_type": draft.source_type.value,
            "title": draft.title[:300],
            "source_date": draft.source_date,
            "content": draft.content,
            "metadata": draft.metadata,
            "created_at": datetime.combine(draft.source_date, datetime.min.time(), tzinfo=UTC),
        }
        chunk_rows = [
            {
                "id": uuid.uuid4(),
                "document_id": document_id,
                "customer_id": customer_id,
                "chunk_index": chunk.index,
                "content": chunk.content,
                "metadata": {
                    "source_type": draft.source_type.value,
                    "title": draft.title,
                    "source_date": draft.source_date.isoformat(),
                    "theme": draft.metadata.get("theme"),
                },
            }
            for chunk in chunk_text(draft.content)
        ]
        results.append((document_row, chunk_rows))
    return results


# --------------------------------------------------------------------------- #
# The demo account
# --------------------------------------------------------------------------- #


def _build_demo_customer(rng: random.Random, as_of: date) -> GeneratedCustomer:
    """The account every demo starts from.

    Characteristics are pinned, not sampled: Enterprise, ~$8,200 MRR, renewal
    roughly a month out, 90-day DAU ~82 falling to ~43, a material support
    increase, NPS 8 → 3, a materially overdue invoice, and email evidence that
    alternatives are being evaluated. The evidence says *evaluating*, never
    *decided*, which is exactly the distinction the verifier must enforce.
    """
    customer_id = uuid.uuid4()
    renewal_date = as_of + timedelta(days=31)
    mrr = 8200.0
    seats = 110

    customer_row = {
        "id": customer_id,
        "external_id": DEMO_EXTERNAL_ID,
        "company_name": DEMO_COMPANY,
        "industry": "Manufacturing",
        "country": "United States",
        "company_size": "1000+",
        "employee_count": 4200,
        "account_tier": AccountTier.ENTERPRISE.value,
        "account_manager": "Avery Chen",
        "scenario_persona": Persona.COMPETITOR_EVALUATION.value,
    }
    subscription_row = {
        "id": uuid.uuid4(),
        "customer_id": customer_id,
        "plan": "Enterprise",
        "monthly_recurring_revenue": mrr,
        "annual_contract_value": round(mrr * 12, 2),
        "contract_start": renewal_date - timedelta(days=365),
        "contract_end": renewal_date,
        "renewal_date": renewal_date,
        "subscription_status": SubscriptionStatus.PAST_DUE.value,
        "seats_purchased": seats,
    }

    # Usage: ~82 DAU across the 90-day baseline, ~43 in the last 30 days.
    usage_rows: list[dict[str, Any]] = []
    for week in range(USAGE_WEEKS):
        offset_days = (USAGE_WEEKS - 1 - week) * USAGE_INTERVAL_DAYS
        usage_date = as_of - timedelta(days=offset_days)
        recent = offset_days <= 30
        active = int(rng.gauss(43, 3)) if recent else int(rng.gauss(82, 5))
        active = max(10, active)
        sessions = int(active * rng.uniform(2.1, 3.4))
        usage_rows.append(
            {
                "id": uuid.uuid4(),
                "customer_id": customer_id,
                "usage_date": usage_date,
                "active_users": active,
                "total_logins": int(sessions * 1.35),
                "sessions": sessions,
                "projects_created": max(0, int(active * 0.08)),
                "api_calls": int(active * rng.uniform(70, 110)),
                "feature_adoption_score": round(rng.uniform(38, 48) if recent else rng.uniform(62, 72), 2),
                "seats_active": max(10, int(active * 1.05)),
            }
        )

    # Support: 3 tickets in the baseline 60 days, 11 in the last 30.
    ticket_rows: list[dict[str, Any]] = []
    counter = 0
    for window_start, window_days, count in ((90, 60, 3), (30, 30, 11)):
        for _ in range(count):
            counter += 1
            created_offset = rng.randint(window_start - window_days, window_start)
            created = datetime.combine(
                as_of - timedelta(days=created_offset), datetime.min.time(), tzinfo=UTC
            ) + timedelta(hours=rng.randint(8, 18))
            recent = created_offset <= 30
            unresolved = recent and counter % 3 == 0
            priority = (
                TicketPriority.CRITICAL
                if unresolved
                else (TicketPriority.HIGH if recent and counter % 2 == 0 else TicketPriority.NORMAL)
            )
            resolution_hours = None if unresolved else round(rng.uniform(26.0, 74.0), 2)
            ticket_rows.append(
                {
                    "id": uuid.uuid4(),
                    "customer_id": customer_id,
                    "external_ticket_id": f"TKT-ACME-{counter:03d}",
                    "created_at": created,
                    "resolved_at": (created + timedelta(hours=resolution_hours) if resolution_hours else None),
                    "category": "Reporting" if counter % 2 else "Integrations",
                    "priority": priority.value,
                    "status": (TicketStatus.ESCALATED.value if unresolved else TicketStatus.RESOLVED.value),
                    "resolution_hours": resolution_hours,
                    "csat_score": None if unresolved else round(rng.uniform(1.5, 3.0) * 2) / 2,
                    "subject": _ticket_subject(rng, "Reporting" if counter % 2 else "Integrations", priority),
                    "description": _ticket_description(
                        rng, "Reporting" if counter % 2 else "Integrations", priority, unresolved
                    ),
                }
            )

    # Billing: latest invoice materially overdue.
    payment_rows: list[dict[str, Any]] = []
    for month in range(6, 0, -1):
        invoice_date = as_of - timedelta(days=month * 30)
        overdue = month == 1
        payment_rows.append(
            {
                "id": uuid.uuid4(),
                "customer_id": customer_id,
                "invoice_date": invoice_date,
                "due_date": invoice_date + timedelta(days=30),
                "amount": mrr,
                "payment_date": None if overdue else invoice_date + timedelta(days=rng.randint(4, 20)),
                "payment_status": (PaymentStatus.OVERDUE.value if overdue else PaymentStatus.PAID.value),
                "days_overdue": 38 if overdue else 0,
            }
        )

    # NPS: 8 → 3.
    nps_rows = [
        {
            "id": uuid.uuid4(),
            "customer_id": customer_id,
            "response_date": as_of - timedelta(days=186),
            "score": 8,
            "feedback": ("Good platform and our analysts rely on it. Reporting flexibility could be better."),
        },
        {
            "id": uuid.uuid4(),
            "customer_id": customer_id,
            "response_date": as_of - timedelta(days=21),
            "score": 3,
            "feedback": (
                "Reporting limitations and slow responses on open tickets have cost us real time "
                "this quarter. We are reassessing ahead of the renewal."
            ),
        },
    ]

    documents = _demo_documents(customer_id, as_of, renewal_date)

    return GeneratedCustomer(
        customer=customer_row,
        subscription=subscription_row,
        usage=usage_rows,
        tickets=ticket_rows,
        payments=payment_rows,
        nps=nps_rows,
        documents=documents,
        outcome={
            "id": uuid.uuid4(),
            "customer_id": customer_id,
            "outcome": CustomerOutcome.UNKNOWN.value,
            "outcome_date": None,
            "churn_reason": None,
            "notes": "Live demo account: renewal pending, high churn risk.",
        },
        persona=Persona.COMPETITOR_EVALUATION,
        renewal_date=renewal_date,
        has_injection=False,
    )


def _demo_documents(
    customer_id: uuid.UUID, as_of: date, renewal_date: date
) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    specs = [
        (
            "CUSTOMER_EMAIL",
            "Platform review ahead of renewal — Acme Corp",
            as_of - timedelta(days=12),
            """Hi Avery,

I want to be straight with you before the renewal conversation. We are evaluating alternative platforms. Competitor X approached our COO directly and we have been asked to run a formal comparison before committing to another year.

Two things are driving it. First, the reporting limitations we have raised since Q1 — our team still rebuilds the monthly pack by hand. Second, price: Competitor X has quoted meaningfully below our current spend.

I am not telling you we are leaving. We have three years of history in the platform and moving would hurt. But I cannot tell you the decision is made either, and I would rather you heard it from me.

If you can show us a credible answer on custom reporting and sharpen the commercial, that changes the conversation.

Dana Whitfield
Director of Operations, Acme Corp""",
        ),
        (
            "CSM_NOTE",
            "Risk review — Acme Corp",
            as_of - timedelta(days=9),
            f"""Account: Acme Corp (CUST-000001). Renewal: {renewal_date.isoformat()}.

Dana confirmed on today's call that a competitive evaluation is underway and named Competitor X. She was careful to say no decision has been taken and that she is not authorised to discuss commercials until their review concludes.

What has changed on our side: daily active users are roughly half what they were a quarter ago, the reporting backlog is still open, and the latest invoice has not been paid — finance told Dana to hold it pending the renewal decision.

Dana also mentioned that their original executive sponsor moved to a different division in the spring, which is why nobody internally is defending the spend.

My read: genuine churn risk, but still winnable. The two levers are a reporting answer and a commercial concession. Do not treat this as a lost account.""",
        ),
        (
            "SUPPORT_SUMMARY",
            "Support escalation history — Acme Corp",
            as_of - timedelta(days=6),
            """Ticket volume for Acme Corp went from 3 in the preceding 60 days to 11 in the last 30.

Two reporting escalations remain open past our target resolution time. CSAT on the tickets that were closed averages below 3. The recurring theme is scheduled exports failing silently and per-recipient report filtering not being available.

The customer's team has started maintaining a manual spreadsheet as a workaround, which is the specific grievance raised in their last email.""",
        ),
        (
            "QBR_NOTE",
            "QBR — Acme Corp (Q previous)",
            as_of - timedelta(days=96),
            """QBR held with the Acme Corp operations team.

At the time, usage was healthy and the relationship was positive — NPS 8, strong adoption in the core module. The one persistent request was custom report scheduling with per-recipient filtering, which has now been open for three quarters.

This note is the baseline the current decline should be read against: the account was in good shape a quarter ago.""",
        ),
        (
            "RENEWAL_NOTE",
            "Renewal preparation — Acme Corp",
            as_of - timedelta(days=3),
            f"""Renewal date {renewal_date.isoformat()}, approximately one month out.

Status: no renewal commitment, competitive evaluation in progress, one invoice 38 days overdue, two support escalations open.

Decision makers: Dana Whitfield (Director of Operations, our main contact) and an unnamed COO-level sponsor on their side. Our original executive sponsor is no longer in the business unit.

Nothing in the record indicates that Acme Corp has cancelled or given notice.""",
        ),
    ]

    results: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    for source_type, title, source_date, content in specs:
        document_id = uuid.uuid4()
        document_row = {
            "id": document_id,
            "customer_id": customer_id,
            "source_type": source_type,
            "title": title,
            "source_date": source_date,
            "content": content.strip(),
            "metadata": {"demo_account": True, "synthetic": True, "theme": "demo"},
            "created_at": datetime.combine(source_date, datetime.min.time(), tzinfo=UTC),
        }
        chunk_rows = [
            {
                "id": uuid.uuid4(),
                "document_id": document_id,
                "customer_id": customer_id,
                "chunk_index": chunk.index,
                "content": chunk.content,
                "metadata": {
                    "source_type": source_type,
                    "title": title,
                    "source_date": source_date.isoformat(),
                    "theme": "demo",
                },
            }
            for chunk in chunk_text(content.strip())
        ]
        results.append((document_row, chunk_rows))
    return results


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


def database_is_seeded(session: Session) -> bool:
    return bool(session.scalar(select(func.count()).select_from(Customer)))


def truncate_customer_data(session: Session) -> None:
    """Remove the synthetic dataset. Workflow rows are left untouched."""
    for model in (
        DocumentChunk,
        CustomerDocument,
        NpsSurvey,
        Payment,
        SupportTicket,
        ProductUsage,
        CustomerOutcomeRecord,
        Subscription,
    ):
        session.execute(delete(model))
    session.execute(delete(Customer))
    session.flush()


def seed_database(
    session: Session,
    *,
    customer_count: int | None = None,
    seed: int | None = None,
    reset: bool = False,
    embed: bool = True,
    batch_size: int = 250,
    as_of: date | None = None,
    progress: Any = None,
) -> SeedStats:
    """Generate and persist the synthetic dataset.

    Idempotent: calling it twice without ``reset`` is a no-op (and says so)
    rather than doubling the dataset.
    """
    settings = get_settings()
    started = datetime.now(tz=UTC)
    count = customer_count or settings.seed_customer_count
    rng = random.Random(seed if seed is not None else settings.seed_random_seed)
    today = as_of or clock_today()
    stats = SeedStats()

    if reset:
        logger.info("resetting customer data before seeding")
        truncate_customer_data(session)
    elif database_is_seeded(session):
        existing = int(session.scalar(select(func.count()).select_from(Customer)) or 0)
        logger.info("database already seeded; skipping", extra={"existing_customers": existing})
        stats.customers = existing
        stats.skipped_existing = True
        return stats

    from app.llm.embeddings import get_embedding_service

    embedder = get_embedding_service() if embed else None

    # Customer 0 is always the pinned demo account; the rest follow the plan.
    outcome_plan = _build_outcome_plan(rng, count)
    outcome_plan[0] = CustomerOutcome.UNKNOWN

    pending: list[GeneratedCustomer] = []
    for index in range(count):
        generated = (
            _build_demo_customer(rng, today)
            if index == 0
            else _generate_customer(rng=rng, index=index, as_of=today, outcome=outcome_plan[index])
        )
        pending.append(generated)
        stats.personas[generated.persona.value] = stats.personas.get(generated.persona.value, 0) + 1
        stats.outcomes[generated.outcome["outcome"]] = stats.outcomes.get(generated.outcome["outcome"], 0) + 1
        if 0 <= (generated.renewal_date - today).days <= 90:
            stats.renewing_90_days += 1
        if generated.has_injection:
            stats.injection_documents += 1

        if len(pending) >= batch_size:
            _flush_batch(session, pending, stats, embedder)
            pending = []
            if progress:
                progress(stats.customers, count)

    if pending:
        _flush_batch(session, pending, stats, embedder)
        if progress:
            progress(stats.customers, count)

    stats.duration_seconds = (datetime.now(tz=UTC) - started).total_seconds()
    logger.info("seed complete", extra=stats.as_dict())
    return stats


def _flush_batch(
    session: Session,
    batch: list[GeneratedCustomer],
    stats: SeedStats,
    embedder: Any,
) -> None:
    """Bulk-insert one batch, embedding all of its chunks in one call."""
    customers = [item.customer for item in batch]
    subscriptions = [item.subscription for item in batch]
    outcomes = [item.outcome for item in batch]
    usage = [row for item in batch for row in item.usage]
    tickets = [row for item in batch for row in item.tickets]
    payments = [row for item in batch for row in item.payments]
    nps = [row for item in batch for row in item.nps]

    documents: list[dict[str, Any]] = []
    chunks: list[dict[str, Any]] = []
    for item in batch:
        for document_row, chunk_rows in item.documents:
            documents.append(document_row)
            chunks.extend(chunk_rows)

    if embedder is not None and chunks:
        vectors, _usage = embedder.embed_texts([chunk["content"] for chunk in chunks])
        for chunk, vector in zip(chunks, vectors, strict=True):
            chunk["embedding"] = vector

    session.execute(insert(Customer), customers)
    session.execute(insert(Subscription), subscriptions)
    if usage:
        session.execute(insert(ProductUsage), usage)
    if tickets:
        session.execute(insert(SupportTicket), tickets)
    if payments:
        session.execute(insert(Payment), payments)
    if nps:
        session.execute(insert(NpsSurvey), nps)
    if documents:
        session.execute(insert(CustomerDocument), documents)
    if chunks:
        session.execute(insert(DocumentChunk), chunks)
    session.execute(insert(CustomerOutcomeRecord), outcomes)
    session.flush()

    stats.customers += len(customers)
    stats.subscriptions += len(subscriptions)
    stats.usage_rows += len(usage)
    stats.tickets += len(tickets)
    stats.payments += len(payments)
    stats.nps += len(nps)
    stats.documents += len(documents)
    stats.chunks += len(chunks)
