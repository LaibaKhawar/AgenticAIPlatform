"""Data agent — deterministic structured retrieval. No LLM.

Candidate generation and metric collection are pure database work, so this agent
calls no model at all. Keeping it in the agent registry (rather than inlining it
in the orchestrator) means the planner can reason about it and the UI can show
which agent produced which task output.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.agents.base import AgentConfig, AgentRunContext, BaseAgent
from app.analytics import metrics as M
from app.core.logging import get_logger
from app.models.enums import AccountTier, AgentType
from app.tools.customer_tools import (
    CustomerRef,
    UpcomingRenewalsInput,
    UpcomingRenewalsOut,
    UsageSummaryInput,
)

logger = get_logger(__name__)


@dataclass
class CandidateSet:
    as_of: date
    window_days: int
    account_tier: str | None
    candidates: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "window_days": self.window_days,
            "account_tier": self.account_tier,
            "total": len(self.candidates),
            "candidates": self.candidates,
        }


@dataclass
class CustomerDataPack:
    """Everything the investigator needs about one customer, all deterministic."""

    customer_id: uuid.UUID
    profile: dict[str, Any]
    subscription: dict[str, Any]
    usage: dict[str, Any]
    support: dict[str, Any]
    payments: dict[str, Any]
    nps: dict[str, Any]
    data_gaps: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "customer_id": str(self.customer_id),
            "profile": self.profile,
            "subscription": self.subscription,
            "usage": self.usage,
            "support": self.support,
            "payments": self.payments,
            "nps": self.nps,
            "data_gaps": self.data_gaps,
        }


class DataAgent(BaseAgent):
    config = AgentConfig(
        agent_type=AgentType.DATA,
        role=(
            "Retrieves candidate accounts and structured customer metrics through validated "
            "repository tools. Performs no model inference."
        ),
        allowed_tools=(
            "find_upcoming_renewals",
            "get_customer_profile",
            "get_subscription",
            "get_usage_summary",
            "get_support_summary",
            "get_payment_summary",
            "get_nps_history",
        ),
        uses_llm=False,
        timeout_seconds=60.0,
    )

    def select_candidates(
        self,
        context: AgentRunContext,
        *,
        window_days: int,
        account_tier: str | None,
        limit: int,
    ) -> CandidateSet:
        with self.traced(context, "candidate_selection"):
            invoker = self.invoker(context)
            result = invoker.call(
                "find_upcoming_renewals",
                UpcomingRenewalsInput(
                    days=window_days,
                    account_tier=AccountTier(account_tier) if account_tier else None,
                    limit=limit,
                ),
            )
            assert isinstance(result, UpcomingRenewalsOut)
            logger.info(
                "candidate accounts selected",
                extra={"window_days": window_days, "tier": account_tier, "count": result.total},
            )
            return CandidateSet(
                as_of=result.as_of,
                window_days=result.window_days,
                account_tier=account_tier,
                candidates=[candidate.model_dump(mode="json") for candidate in result.customers],
            )

    def collect_customer_data(self, context: AgentRunContext, *, customer_id: uuid.UUID) -> CustomerDataPack:
        """One pack per customer, with explicit data gaps instead of silence."""
        with self.traced(context, "structured_data_retrieval"):
            invoker = self.invoker(context)
            ref = CustomerRef(customer_id=str(customer_id))
            profile = invoker.call("get_customer_profile", ref)
            subscription = invoker.call("get_subscription", ref)
            usage = invoker.call("get_usage_summary", UsageSummaryInput(customer_id=str(customer_id)))
            support = invoker.call("get_support_summary", ref)
            payments = invoker.call("get_payment_summary", ref)
            nps = invoker.call("get_nps_history", ref)

            gaps: list[str] = []
            if not subscription.found:  # type: ignore[attr-defined]
                gaps.append("No subscription record, so renewal timing and contract value are unknown.")
            if usage.data_points == 0:  # type: ignore[attr-defined]
                gaps.append("No product-usage history is recorded for this account.")
            elif usage.active_user_change_pct is None:  # type: ignore[attr-defined]
                gaps.append("Usage history is too short to compute a period-over-period change.")
            if support.recent_ticket_count == 0 and support.baseline_ticket_count == 0:  # type: ignore[attr-defined]
                gaps.append("No support tickets are recorded, so support sentiment is unknown.")
            if support.average_csat is None:  # type: ignore[attr-defined]
                gaps.append("No CSAT responses are available.")
            if nps.latest_score is None:  # type: ignore[attr-defined]
                gaps.append("No NPS response is on record.")
            if payments.invoice_count == 0:  # type: ignore[attr-defined]
                gaps.append("No invoices are recorded, so billing health is unknown.")

            return CustomerDataPack(
                customer_id=customer_id,
                profile=profile.model_dump(mode="json"),
                subscription=subscription.model_dump(mode="json"),
                usage=usage.model_dump(mode="json"),
                support=support.model_dump(mode="json"),
                payments=payments.model_dump(mode="json"),
                nps=nps.model_dump(mode="json"),
                data_gaps=gaps,
            )

    @staticmethod
    def days_to_renewal(renewal_date: date | None, *, as_of: date) -> int | None:
        return M.days_until_renewal(renewal_date, as_of=as_of)
