"""Risk agent — deterministic screening and ranking. No LLM.

Screens every candidate with the heuristic model in one batch (five queries,
not 5N) and selects the accounts worth an LLM investigation. Cost control is
structural: the expensive agents only ever see the shortlist.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.agents.base import AgentConfig, AgentRunContext, BaseAgent
from app.analytics import metrics as M
from app.analytics.risk import RiskAssessment, assess_risk
from app.core.clock import today
from app.core.logging import get_logger
from app.models.enums import AgentType
from app.repositories.customers import CustomerRepository

logger = get_logger(__name__)


@dataclass
class ScreeningResult:
    as_of: date
    threshold: float
    assessments: dict[uuid.UUID, RiskAssessment] = field(default_factory=dict)
    selected: list[uuid.UUID] = field(default_factory=list)
    below_threshold: int = 0

    def as_dict(self, *, company_names: dict[uuid.UUID, str] | None = None) -> dict[str, Any]:
        names = company_names or {}
        ranked = sorted(self.assessments.values(), key=lambda a: a.score, reverse=True)
        return {
            "as_of": self.as_of.isoformat(),
            "threshold": self.threshold,
            "screened": len(self.assessments),
            "selected": [str(customer_id) for customer_id in self.selected],
            "below_threshold": self.below_threshold,
            "ranking": [
                {
                    "customer_id": assessment.customer_id,
                    "company_name": names.get(uuid.UUID(assessment.customer_id), ""),
                    "score": assessment.score,
                    "level": assessment.level.value,
                    "days_to_renewal": assessment.days_to_renewal,
                    "coverage": assessment.coverage,
                    "top_signals": [
                        {"key": signal.key, "label": signal.label, "contribution": signal.contribution}
                        for signal in assessment.top_signals[:3]
                    ],
                }
                for assessment in ranked[:50]
            ],
        }


class RiskAgent(BaseAgent):
    config = AgentConfig(
        agent_type=AgentType.RISK,
        role=(
            "Computes the deterministic churn-risk score for every candidate account and ranks "
            "them. Transparent weighted heuristic, no model inference."
        ),
        allowed_tools=("get_risk_signals",),
        uses_llm=False,
        timeout_seconds=120.0,
    )

    def screen(
        self,
        context: AgentRunContext,
        *,
        customer_ids: list[uuid.UUID],
        threshold: float,
        max_accounts: int,
        as_of: date | None = None,
    ) -> ScreeningResult:
        reference_date = as_of or today()
        with self.traced(context, "risk_screening"):
            repository = CustomerRepository(context.session)
            bundles = repository.load_bundles(customer_ids)

            assessments: dict[uuid.UUID, RiskAssessment] = {}
            for customer_id, bundle in bundles.items():
                windows = M.summarise_usage_windows(bundle.usage, as_of=reference_date)
                assessments[customer_id] = assess_risk(
                    customer_id=str(customer_id),
                    usage=windows,
                    support=M.summarise_support(bundle.tickets, as_of=reference_date),
                    payments=M.calculate_payment_delinquency(bundle.payments, as_of=reference_date),
                    nps=M.get_latest_nps(bundle.nps_surveys),
                    seats_purchased=bundle.subscription.seats_purchased if bundle.subscription else None,
                    renewal_date=bundle.subscription.renewal_date if bundle.subscription else None,
                    as_of=reference_date,
                )

            ranked = sorted(assessments.values(), key=lambda a: a.score, reverse=True)
            above = [a for a in ranked if a.score >= threshold]
            selected = [uuid.UUID(a.customer_id) for a in above[:max_accounts]]

            logger.info(
                "risk screening completed",
                extra={
                    "screened": len(assessments),
                    "above_threshold": len(above),
                    "selected": len(selected),
                    "threshold": threshold,
                },
            )
            return ScreeningResult(
                as_of=reference_date,
                threshold=threshold,
                assessments=assessments,
                selected=selected,
                below_threshold=len(assessments) - len(above),
            )
