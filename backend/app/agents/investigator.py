"""Investigator agent.

Consumes deterministic metrics + retrieved evidence for one customer and
produces a typed :class:`InvestigationResult`: risk interpretation, cited
material claims, and recommended actions.

Guardrails applied after the model returns, in code:

* evidence references are validated against the evidence actually retrieved for
  *this run and this customer* — a hallucinated ``EV-99`` is stripped and the
  claim is flagged, never silently accepted;
* the model's risk score is clamped into a band around the deterministic score
  (:func:`app.analytics.risk.blend_scores`);
* the risk level is recomputed from the final score rather than trusted.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from app.agents.base import AgentConfig, AgentRunContext, BaseAgent, system_prompt
from app.agents.data_agent import CustomerDataPack
from app.agents.retrieval_agent import EvidenceSet
from app.analytics.risk import RiskAssessment, blend_scores, risk_level_for
from app.core.logging import get_logger
from app.llm.client import CallRecord, json_preview
from app.models.enums import AgentType, ClaimType
from app.rag.sanitize import UNTRUSTED_DATA_RULES, render_evidence_block
from app.schemas.agent import ClaimDraft, InvestigationResult

logger = get_logger(__name__)


@dataclass
class InvestigationOutcome:
    result: InvestigationResult
    heuristic_score: float
    invalid_references: dict[str, list[str]] = field(default_factory=dict)
    dropped_claims: list[str] = field(default_factory=list)
    call_record: CallRecord | None = None

    @property
    def had_hallucinated_evidence(self) -> bool:
        return bool(self.invalid_references)


class InvestigatorAgent(BaseAgent):
    config = AgentConfig(
        agent_type=AgentType.INVESTIGATOR,
        role=(
            "Interprets one account's deterministic signals and retrieved evidence into cited, "
            "typed material claims and recommended retention actions."
        ),
        # Read-only by design: the investigator cannot propose_customer_action.
        allowed_tools=(
            "get_customer_profile",
            "get_subscription",
            "get_usage_summary",
            "get_support_summary",
            "get_payment_summary",
            "get_nps_history",
            "get_risk_signals",
            "search_customer_documents",
        ),
        timeout_seconds=180.0,
        max_retries=2,
    )

    def output_schema_name(self) -> str:
        return InvestigationResult.__name__

    def investigate(
        self,
        context: AgentRunContext,
        *,
        data_pack: CustomerDataPack,
        assessment: RiskAssessment,
        evidence: EvidenceSet,
        objective: str,
    ) -> InvestigationOutcome:
        with self.traced(context, "customer_investigation"):
            result, record = self.call_model(
                context,
                operation="investigate",
                system_prompt=_system_prompt(),
                user_prompt=_user_prompt(objective, data_pack, assessment, evidence),
                output_model=InvestigationResult,
                payload={
                    "customer": data_pack.profile,
                    "signals": [signal.to_dict() for signal in assessment.top_signals],
                    "evidence": evidence.as_prompt_payload(),
                    "heuristic_score": assessment.score,
                    "metrics": _metric_payload(data_pack, assessment),
                    "data_gaps": data_pack.data_gaps,
                },
            )

            valid_references = set(evidence.references)
            sanitised_claims: list[ClaimDraft] = []
            invalid: dict[str, list[str]] = {}
            dropped: list[str] = []

            for claim in result.claims:
                bad = [ref for ref in claim.evidence_references if ref not in valid_references]
                good = [ref for ref in claim.evidence_references if ref in valid_references]
                if bad:
                    invalid[claim.key] = bad
                    logger.warning(
                        "investigator cited evidence that does not exist",
                        extra={
                            "customer_id": str(data_pack.customer_id),
                            "claim_key": claim.key,
                            "invalid_references": bad,
                        },
                    )
                if not good and claim.claim_type in {
                    ClaimType.OBSERVED_FACT,
                    ClaimType.CALCULATED_METRIC,
                }:
                    # A factual claim with no surviving citation cannot be
                    # reported. Record it as dropped rather than hiding it.
                    dropped.append(claim.key)
                    continue
                sanitised_claims.append(claim.model_copy(update={"evidence_references": good}))

            final_score = blend_scores(assessment.score, result.risk_score)
            final = result.model_copy(
                update={
                    "claims": sanitised_claims,
                    "risk_score": final_score,
                    "risk_level": risk_level_for(final_score),
                }
            )

            logger.info(
                "investigation produced",
                extra={
                    "customer_id": str(data_pack.customer_id),
                    "claims": len(sanitised_claims),
                    "dropped_claims": len(dropped),
                    "invalid_reference_claims": len(invalid),
                    "heuristic_score": assessment.score,
                    "final_score": final_score,
                },
            )
            return InvestigationOutcome(
                result=final,
                heuristic_score=assessment.score,
                invalid_references=invalid,
                dropped_claims=dropped,
                call_record=record,
            )


def _system_prompt() -> str:
    return system_prompt(
        "Your role: INVESTIGATOR.\n\n"
        "You investigate ONE customer account for churn risk and produce an InvestigationResult.\n\n"
        f"{UNTRUSTED_DATA_RULES}\n\n"
        "Claim rules:\n"
        "- claim_type=CALCULATED_METRIC: a number the platform computed. Restate it exactly as "
        "given and cite the metric evidence reference it came from. Never recompute it.\n"
        "- claim_type=OBSERVED_FACT: something a document or record states. Cite that evidence and "
        "stay within what it literally says.\n"
        "- claim_type=INFERENCE: your interpretation. Use hedged language ('appears to', 'suggests', "
        "'may'). Never present an inference as an observed fact.\n\n"
        "Critical distinction: evidence saying a customer is *evaluating alternatives* supports "
        "'the customer is evaluating alternatives'. It does NOT support 'the customer has decided "
        "to cancel'. Do not upgrade exploratory language into a settled decision.\n\n"
        "The risk score you return will be clamped to within 15 points of the platform's "
        "deterministic score, so use it to express interpretation, not to override the model.\n\n"
        "List anything you could not determine in data_gaps. Recommend actions from the schema's "
        "action_type enum only; the platform decides which of them need human approval."
    )


def _user_prompt(
    objective: str,
    data_pack: CustomerDataPack,
    assessment: RiskAssessment,
    evidence: EvidenceSet,
) -> str:
    evidence_block = render_evidence_block(
        [
            {
                "reference": item.reference,
                "source_type": item.source_type,
                "source_date": item.source_date.isoformat() if item.source_date else "",
                "content": item.content,
            }
            for item in evidence.items
        ]
    )
    signals = (
        "\n".join(
            f"- {signal.label} [{signal.key}]: value={signal.value}{signal.unit} "
            f"severity={signal.severity:.2f} contribution={signal.contribution:.1f} pts — {signal.detail}"
            for signal in assessment.top_signals
        )
        or "- (no material signals were computed)"
    )

    gaps = "\n".join(f"- {gap}" for gap in data_pack.data_gaps) or "- (none)"

    return (
        f"Run objective:\n{objective}\n\n"
        f"ACCOUNT\n{json_preview(data_pack.profile)}\n\n"
        f"SUBSCRIPTION\n{json_preview(data_pack.subscription)}\n\n"
        f"USAGE (platform-computed)\n{json_preview(data_pack.usage)}\n\n"
        f"SUPPORT (platform-computed)\n{json_preview(data_pack.support)}\n\n"
        f"BILLING (platform-computed)\n{json_preview(data_pack.payments)}\n\n"
        f"NPS (platform-computed)\n{json_preview(data_pack.nps)}\n\n"
        f"DETERMINISTIC RISK ASSESSMENT\n"
        f"score={assessment.score}/100 level={assessment.level.value} "
        f"coverage={assessment.coverage:.2f} days_to_renewal={assessment.days_to_renewal}\n"
        f"{signals}\n\n"
        f"KNOWN DATA GAPS\n{gaps}\n\n"
        f"AVAILABLE EVIDENCE REFERENCES: {', '.join(evidence.references) or '(none)'}\n"
        "You may only cite these references. Citing anything else is a defect.\n\n"
        f"{evidence_block}\n\n"
        f"Return the InvestigationResult for customer_external_id="
        f"{data_pack.profile.get('external_id')}."
    )


def _metric_payload(data_pack: CustomerDataPack, assessment: RiskAssessment) -> dict[str, Any]:
    return {
        "heuristic_risk_score": assessment.score,
        "risk_level": assessment.level.value,
        "days_to_renewal": assessment.days_to_renewal,
        "coverage": assessment.coverage,
        "monthly_recurring_revenue": data_pack.subscription.get("monthly_recurring_revenue"),
        "annual_contract_value": data_pack.subscription.get("annual_contract_value"),
        "active_user_change_pct": data_pack.usage.get("active_user_change_pct"),
        "usage_change_pct": data_pack.usage.get("usage_change_pct"),
        "seat_utilization": data_pack.usage.get("seat_utilization"),
        "ticket_growth_pct": data_pack.support.get("ticket_growth_pct"),
        "average_csat": data_pack.support.get("average_csat"),
        "latest_nps": data_pack.nps.get("latest_score"),
        "max_days_overdue": data_pack.payments.get("max_days_overdue"),
    }


def customer_uuid(data_pack: CustomerDataPack) -> uuid.UUID:
    return data_pack.customer_id
