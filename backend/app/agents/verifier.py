"""Verifier agent.

An *independent* pass over every material claim. Independence matters: the
verifier is a separate call with a separate prompt that sees the claim and its
evidence but not the investigator's reasoning, so it cannot inherit the
investigator's confidence.

Verification is deliberately not "ask the model if it's right". It is a
three-stage pipeline:

1. **Programmatic evidence validation** — do the cited references exist, belong
   to this run, and belong to this customer? A hallucinated reference is an
   automatic UNSUPPORTED with no model involvement.
2. **Deterministic rules** (:mod:`app.analytics.claim_rules`) — certainty
   upgrades, unmatched numbers and weak claim/evidence overlap. A rule veto is
   final and cannot be overridden by the model.
3. **Model judgement** — only for claims that survive 1 and 2, and only able to
   *downgrade* a claim or supply a revision, never to promote one above what the
   rules allow.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from app.agents.base import AgentConfig, AgentRunContext, BaseAgent, system_prompt
from app.analytics.claim_rules import evaluate_claim, hedge_claim
from app.core.logging import get_logger
from app.llm.client import CallRecord
from app.models.enums import AgentType, ClaimStatus
from app.models.workflow import Claim
from app.rag.sanitize import UNTRUSTED_DATA_RULES, render_evidence_block
from app.schemas.agent import ClaimVerification, VerificationBatch

logger = get_logger(__name__)

# Rank used to make sure the model can only make a claim weaker, never stronger.
_STRENGTH: dict[ClaimStatus, int] = {
    ClaimStatus.SUPPORTED: 3,
    ClaimStatus.PARTIALLY_SUPPORTED: 2,
    ClaimStatus.UNSUPPORTED: 1,
    ClaimStatus.CONTRADICTED: 0,
    ClaimStatus.PENDING: 4,
}


@dataclass
class ClaimVerdict:
    claim_key: str
    status: ClaimStatus
    confidence: float
    reason: str
    suggested_revision: str | None
    final_text: str | None
    checked_references: list[str] = field(default_factory=list)
    invalid_references: list[str] = field(default_factory=list)
    decided_by: str = "rules"  # rules | model | programmatic

    @property
    def usable_in_report(self) -> bool:
        return self.status in {ClaimStatus.SUPPORTED, ClaimStatus.PARTIALLY_SUPPORTED}


@dataclass
class VerificationOutcome:
    verdicts: list[ClaimVerdict] = field(default_factory=list)
    call_record: CallRecord | None = None

    def by_key(self) -> dict[str, ClaimVerdict]:
        return {verdict.claim_key: verdict for verdict in self.verdicts}

    def stats(self) -> dict[str, Any]:
        total = len(self.verdicts)
        counts: dict[str, int] = {}
        for verdict in self.verdicts:
            counts[verdict.status.value] = counts.get(verdict.status.value, 0) + 1
        supported = counts.get(ClaimStatus.SUPPORTED.value, 0)
        rejected = counts.get(ClaimStatus.UNSUPPORTED.value, 0) + counts.get(ClaimStatus.CONTRADICTED.value, 0)
        return {
            "total": total,
            "counts": counts,
            "supported": supported,
            "rejected": rejected,
            "supported_pct": round(supported / total * 100, 2) if total else None,
            "unsupported_pct": round(rejected / total * 100, 2) if total else None,
            "decided_by_rules": sum(1 for v in self.verdicts if v.decided_by != "model"),
        }


class VerifierAgent(BaseAgent):
    config = AgentConfig(
        agent_type=AgentType.VERIFIER,
        role=(
            "Independently checks every material claim against its cited evidence, rejecting "
            "unsupported claims and rewriting over-stated ones."
        ),
        allowed_tools=(),
        temperature=0.0,
        timeout_seconds=180.0,
        max_retries=2,
    )

    def output_schema_name(self) -> str:
        return VerificationBatch.__name__

    def verify(
        self,
        context: AgentRunContext,
        *,
        claims: list[Claim],
        run_id: uuid.UUID,
    ) -> VerificationOutcome:
        if not claims:
            return VerificationOutcome()

        with self.traced(context, "verification"):
            prepared: list[dict[str, Any]] = []
            verdicts: dict[str, ClaimVerdict] = {}

            for claim in claims:
                evidence_items = [
                    item
                    for item in claim.evidence_items
                    # Programmatic validation: same run, same customer.
                    if item.run_id == run_id and (claim.customer_id is None or item.customer_id == claim.customer_id)
                ]
                invalid = [item.reference for item in claim.evidence_items if item not in evidence_items]
                texts = [item.content for item in evidence_items]

                rule_result = evaluate_claim(
                    claim.claim_text,
                    texts,
                    has_valid_evidence=bool(evidence_items),
                    claim_type=claim.claim_type,
                )

                if rule_result.is_veto:
                    verdicts[claim.claim_key] = ClaimVerdict(
                        claim_key=claim.claim_key,
                        status=rule_result.status or ClaimStatus.UNSUPPORTED,
                        confidence=0.9,
                        reason=rule_result.reason,
                        suggested_revision=rule_result.suggested_revision,
                        final_text=rule_result.suggested_revision,
                        checked_references=[item.reference for item in evidence_items],
                        invalid_references=invalid,
                        decided_by="programmatic" if not evidence_items else "rules",
                    )
                    continue

                prepared.append(
                    {
                        "key": claim.claim_key,
                        "text": claim.claim_text,
                        "claim_type": claim.claim_type,
                        "has_valid_evidence": bool(evidence_items),
                        "rule_hint": {
                            "overlap": rule_result.overlap,
                            "advisory_status": rule_result.status.value if rule_result.status else None,
                            "note": rule_result.reason,
                        },
                        "evidence": [
                            {
                                "reference": item.reference,
                                "source_type": item.source_type,
                                "source_date": item.source_date.isoformat() if item.source_date else None,
                                "content": item.content,
                            }
                            for item in evidence_items
                        ],
                    }
                )
                # Ceiling the model cannot exceed.
                verdicts[claim.claim_key] = ClaimVerdict(
                    claim_key=claim.claim_key,
                    status=rule_result.status or ClaimStatus.SUPPORTED,
                    confidence=0.6,
                    reason=rule_result.reason,
                    suggested_revision=rule_result.suggested_revision,
                    final_text=None,
                    checked_references=[item["reference"] for item in prepared[-1]["evidence"]],
                    invalid_references=invalid,
                    decided_by="rules",
                )

            record: CallRecord | None = None
            if prepared:
                batch, record = self.call_model(
                    context,
                    operation="verify",
                    system_prompt=_system_prompt(),
                    user_prompt=_user_prompt(prepared),
                    output_model=VerificationBatch,
                    payload={"claims": prepared},
                )
                for verification in batch.verifications:
                    existing = verdicts.get(verification.claim_key)
                    if existing is None:
                        # The model invented a claim key; ignore it.
                        logger.warning(
                            "verifier returned a verdict for an unknown claim",
                            extra={"claim_key": verification.claim_key},
                        )
                        continue
                    verdicts[verification.claim_key] = _merge_verdict(existing, verification, claims)

            claim_types = {claim.claim_key: claim.claim_type for claim in claims}
            claim_texts = {claim.claim_key: claim.claim_text for claim in claims}
            final = [
                _finalise(verdict, claim_types.get(key, ""), claim_texts.get(key, ""))
                for key, verdict in verdicts.items()
            ]
            outcome = VerificationOutcome(verdicts=final, call_record=record)
            logger.info("claims verified", extra=outcome.stats())
            return outcome


def _merge_verdict(rules_verdict: ClaimVerdict, model: ClaimVerification, claims: list[Claim]) -> ClaimVerdict:
    """Combine the rule ceiling with the model's judgement.

    The model may only weaken a claim. If the rules said PARTIALLY_SUPPORTED and
    the model says SUPPORTED, the result stays PARTIALLY_SUPPORTED.
    """
    ceiling = rules_verdict.status
    chosen = model.status
    if _STRENGTH[chosen] > _STRENGTH[ceiling]:
        chosen = ceiling
        reason = f"{model.reasoning} (capped by deterministic rules: {rules_verdict.reason})"
        decided_by = "rules"
    else:
        reason = model.reasoning
        decided_by = "model"
    return ClaimVerdict(
        claim_key=rules_verdict.claim_key,
        status=chosen,
        confidence=round(min(model.confidence, 0.98), 3),
        reason=reason,
        suggested_revision=model.suggested_revision or rules_verdict.suggested_revision,
        final_text=None,
        checked_references=rules_verdict.checked_references,
        invalid_references=rules_verdict.invalid_references,
        decided_by=decided_by,
    )


def _finalise(verdict: ClaimVerdict, claim_type: str, original_text: str) -> ClaimVerdict:
    """Decide the text (if any) the report may use for this claim.

    * SUPPORTED      → the claim as written.
    * PARTIALLY_...  → the verifier's revision, or a deterministically hedged
      rewrite. A partially supported finding is reported *with its qualifier*
      rather than discarded: "the evidence points this way but does not prove
      it" is useful to a reader, silence is not.
    * UNSUPPORTED / CONTRADICTED → no reportable text at all. These appear only
      in the excluded-conclusions list, with the reason they were rejected.
    """
    if verdict.status is ClaimStatus.SUPPORTED:
        verdict.final_text = original_text
    elif verdict.status is ClaimStatus.PARTIALLY_SUPPORTED:
        verdict.final_text = verdict.suggested_revision or hedge_claim(original_text)
    else:
        verdict.final_text = None
    return verdict


def _system_prompt() -> str:
    return system_prompt(
        "Your role: VERIFIER.\n\n"
        "For each claim you are given the claim text and ONLY the evidence cited for it. Decide "
        "whether that evidence supports that wording:\n"
        "- SUPPORTED: the evidence states this, at this strength.\n"
        "- PARTIALLY_SUPPORTED: the direction is right but the wording overstates, generalises or "
        "adds detail the evidence lacks. Provide suggested_revision with wording the evidence does "
        "support.\n"
        "- UNSUPPORTED: the evidence does not establish this claim.\n"
        "- CONTRADICTED: the evidence says something incompatible with the claim.\n\n"
        f"{UNTRUSTED_DATA_RULES}\n\n"
        "Be strict about certainty. 'We are evaluating alternative platforms' supports 'the "
        "customer is evaluating alternatives' and CONTRADICTS 'the customer has decided to "
        "cancel'. Numbers in a claim must appear in the evidence.\n\n"
        "You are reviewing another agent's work. Do not assume it is correct. Deterministic rules "
        "have already screened these claims and their advisory note is included; you may agree or "
        "be stricter, but you cannot be more permissive — the platform enforces that."
    )


def _user_prompt(prepared: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for item in prepared:
        evidence_block = render_evidence_block(
            [
                {
                    "reference": evidence["reference"],
                    "source_type": evidence["source_type"],
                    "source_date": evidence["source_date"] or "",
                    "content": evidence["content"],
                }
                for evidence in item["evidence"]
            ]
        )
        blocks.append(
            f"CLAIM key={item['key']} type={item['claim_type']}\n"
            f"text: {item['text']}\n"
            f"deterministic note: {item['rule_hint']['note']} "
            f"(term overlap {item['rule_hint']['overlap']:.0%}, advisory "
            f"{item['rule_hint']['advisory_status'] or 'none'})\n"
            f"{evidence_block}"
        )
    return (
        f"Verify {len(prepared)} claim(s). Return one verification per claim, keyed by claim_key.\n\n"
        + "\n\n====\n\n".join(blocks)
    )
