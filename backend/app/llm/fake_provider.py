"""Deterministic local model.

This is a *scripted model*, not a stub that returns fixed strings. It derives
its output from the real inputs it is given (computed risk signals, retrieved
evidence, verification rules), which is what makes the end-to-end tests
meaningful without a paid API key:

* ``plan``      → the canonical churn-investigation DAG, shaped by operator parameters.
* ``investigate`` → risk factors and cited claims derived from the deterministic
  signals and the retrieved evidence text.
* ``verify``    → the deterministic rules in :mod:`app.analytics.claim_rules`.
* ``report``    → narrative assembled from the verified material it is handed.

Two behaviours are deliberate and documented:

1. The investigator emits exactly one *over-reaching* claim when the evidence
   contains an exploratory intent signal ("evaluating alternative platforms").
   That claim asserts a settled cancellation decision, and the verifier is
   expected to reject it. This keeps the hallucination-mitigation path on the
   happy path of every demo and test run instead of only in unit tests.
2. Output is a pure function of the inputs, so the same run produces the same
   report twice — which is what lets the evaluation harness attribute changes to
   code rather than sampling noise.
"""

from __future__ import annotations

import hashlib
import re
import time
from typing import Any

from app.analytics.claim_rules import HEDGE_PHRASES, classify_with_rules
from app.core.config import get_settings
from app.core.errors import StructuredOutputError
from app.llm.base import EmbeddingResponse, LLMRequest, LLMResponse, LLMUsage, estimate_tokens
from app.llm.embeddings import local_embedding
from app.models.enums import ActionType, ClaimType, RiskLevel

# Evidence phrases that make a competitive-evaluation signal explicit.
_INTENT_PHRASES = (
    "alternative platform",
    "alternative vendor",
    "competitor",
    "competitive evaluation",
    "other vendors",
    "rfp",
    "benchmarking against",
)

_SENTIMENT_NEGATIVE = (
    "frustrat",
    "disappoint",
    "escalat",
    "blocker",
    "blocking",
    "unaccept",
    "churn",
    "cancel",
    "downgrade",
    "budget cut",
    "pricing pressure",
    "too expensive",
    "slow",
    "broken",
    "regression",
    "lost",
    "left the company",
    "sponsor",
    "concern",
)


class FakeLLMProvider:
    """Deterministic, offline provider used by default and by every test."""

    name = "fake"

    def __init__(self, *, model: str | None = None) -> None:
        settings = get_settings()
        self.model = model or f"deterministic-{settings.llm_model}"
        self.calls: list[LLMRequest] = []

    # --- provider API -----------------------------------------------------

    def generate_json(self, request: LLMRequest) -> LLMResponse:
        started = time.perf_counter()
        self.calls.append(request)
        handler = {
            "plan": self._plan,
            "investigate": self._investigate,
            "verify": self._verify,
            "report": self._report,
        }.get(request.operation)
        if handler is None:
            raise StructuredOutputError(f"fake provider has no handler for operation '{request.operation}'")
        payload = handler(request)
        latency_ms = max(1, int((time.perf_counter() - started) * 1000))
        completion_text = str(payload)
        return LLMResponse(
            payload=payload,
            usage=LLMUsage(
                provider=self.name,
                model=self.model,
                prompt_tokens=estimate_tokens(request.prompt_text),
                completion_tokens=estimate_tokens(completion_text),
                latency_ms=latency_ms,
            ),
            raw_text=completion_text,
        )

    def embed(self, texts: list[str]) -> EmbeddingResponse:
        return EmbeddingResponse(
            vectors=[local_embedding(text) for text in texts],
            usage=LLMUsage(
                provider=self.name,
                model="deterministic-hash-embedding",
                prompt_tokens=sum(estimate_tokens(text) for text in texts),
            ),
        )

    # --- planner ----------------------------------------------------------

    def _plan(self, request: LLMRequest) -> dict[str, Any]:
        context = request.context
        objective: str = context.get("objective", "")
        params: dict[str, Any] = context.get("parameters", {}) or {}
        renewal_window = params.get("renewal_window_days", 90)
        max_accounts = params.get("max_accounts", 5)
        tier = params.get("account_tier")

        tier_text = f"{tier.replace('_', ' ').lower()} " if tier else ""
        tasks = [
            {
                "id": "select_candidates",
                "agent": "data",
                "stage": "candidate_selection",
                "description": (
                    f"Retrieve {tier_text}accounts with a renewal date inside the next "
                    f"{renewal_window} days using validated repository queries."
                ),
                "dependencies": [],
                "parameters": {
                    "renewal_window_days": renewal_window,
                    "account_tier": tier,
                },
            },
            {
                "id": "screen_risk",
                "agent": "risk",
                "stage": "risk_screening",
                "description": (
                    "Compute the deterministic churn-risk score for every candidate and select "
                    f"the top {max_accounts} accounts for investigation."
                ),
                "dependencies": ["select_candidates"],
                "parameters": {"max_accounts": max_accounts},
            },
            {
                "id": "investigate_accounts",
                "agent": "investigator",
                "stage": "account_investigations",
                "description": (
                    "Investigate each selected account: structured metrics plus semantic evidence "
                    "retrieval, producing cited material claims."
                ),
                "dependencies": ["screen_risk"],
                "parameters": {},
            },
            {
                "id": "verify_claims",
                "agent": "verifier",
                "stage": "claim_verification",
                "description": (
                    "Independently verify every material claim against its cited evidence and "
                    "reject or rewrite anything the evidence does not support."
                ),
                "dependencies": ["investigate_accounts"],
                "parameters": {},
            },
            {
                "id": "generate_report",
                "agent": "reporter",
                "stage": "report_generation",
                "description": "Compose the executive report from verified conclusions only.",
                "dependencies": ["verify_claims"],
                "parameters": {},
            },
            {
                "id": "request_approvals",
                "agent": "policy",
                "stage": "approval",
                "description": (
                    "Apply the deterministic sensitive-action policy and open approval requests "
                    "for any customer-facing or write action."
                ),
                "dependencies": ["generate_report"],
                "parameters": {},
            },
            {
                "id": "finalize",
                "agent": "system",
                "stage": "completion",
                "description": "Close out the run once every approval has been resolved.",
                "dependencies": ["request_approvals"],
                "parameters": {},
            },
        ]
        return {
            "objective": objective,
            "workflow_type": "churn_investigation",
            "reasoning": (
                "Deterministic selection and scoring first so the LLM only reasons about the "
                "accounts that matter; verification is a separate task so claims are judged "
                "independently of the agent that produced them."
            ),
            "tasks": tasks,
        }

    # --- investigator -----------------------------------------------------

    def _investigate(self, request: LLMRequest) -> dict[str, Any]:
        context = request.context
        customer: dict[str, Any] = context.get("customer", {})
        signals: list[dict[str, Any]] = context.get("signals", []) or []
        evidence: list[dict[str, Any]] = context.get("evidence", []) or []
        heuristic_score: float = float(context.get("heuristic_score", 0.0))
        metrics: dict[str, Any] = context.get("metrics", {}) or {}
        data_gaps: list[str] = list(context.get("data_gaps", []) or [])
        external_id = customer.get("external_id", "unknown")
        company = customer.get("company_name", "The account")

        material_signals = [s for s in signals if (s.get("severity") or 0) >= 0.25][:6]
        risk_factors = [
            {
                "factor": signal["label"],
                "explanation": signal.get("detail", ""),
                "severity": _severity_to_level(signal.get("severity", 0.0)).value,
                "evidence_references": _references_for_signal(signal, evidence),
            }
            for signal in material_signals
        ]

        claims: list[dict[str, Any]] = []

        # 1. Calculated-metric claims, each citing the metric evidence row.
        for signal in material_signals[:4]:
            reference = _metric_reference(signal, evidence)
            if reference is None:
                continue
            value = signal.get("value")
            claims.append(
                {
                    "key": f"metric_{signal['key']}",
                    "text": _metric_claim_text(company, signal, value),
                    "claim_type": ClaimType.CALCULATED_METRIC.value,
                    "confidence": round(min(0.95, 0.7 + signal.get("severity", 0) / 4), 3),
                    "evidence_references": [reference],
                }
            )

        # 2. Observed-fact claims grounded in retrieved document text.
        qualitative = [item for item in evidence if item.get("source_type") == "DOCUMENT_CHUNK"]
        for item in qualitative[:3]:
            sentence = _salient_sentence(item.get("content", ""))
            if not sentence:
                continue
            claims.append(
                {
                    "key": f"doc_{item['reference'].lower().replace('-', '_')}",
                    "text": _observed_claim_text(company, sentence),
                    "claim_type": ClaimType.OBSERVED_FACT.value,
                    "confidence": 0.78,
                    "evidence_references": [item["reference"]],
                }
            )

        # 3. One deliberate over-reach when an intent signal is present, so the
        #    verification path is exercised on every run (see module docstring).
        intent_item = _find_intent_evidence(qualitative)
        if intent_item is not None:
            claims.append(
                {
                    "key": "intent_overreach",
                    "text": f"{company} has decided to cancel their contract at renewal.",
                    "claim_type": ClaimType.OBSERVED_FACT.value,
                    "confidence": 0.62,
                    "evidence_references": [intent_item["reference"]],
                }
            )

        # 4. A properly hedged inference tying the picture together.
        if material_signals:
            top = material_signals[0]
            claims.append(
                {
                    "key": "overall_inference",
                    "text": (
                        f"{company} appears to be at elevated churn risk, driven primarily by {top['label'].lower()}."
                    ),
                    "claim_type": ClaimType.INFERENCE.value,
                    "confidence": round(min(0.9, 0.5 + heuristic_score / 200), 3),
                    "evidence_references": [item["reference"] for item in evidence[:3] if item.get("reference")],
                }
            )

        actions = _recommended_actions(heuristic_score, material_signals, metrics)
        level = _score_to_level(heuristic_score)
        summary = _investigation_summary(company, heuristic_score, level, material_signals, metrics, data_gaps)

        # The fake stays inside the blend band the application enforces anyway.
        adjustment = 4.0 if intent_item is not None else 0.0
        return {
            "customer_external_id": external_id,
            "risk_score": round(min(100.0, heuristic_score + adjustment), 2),
            "risk_level": level.value,
            "confidence": round(min(0.92, 0.45 + 0.05 * len(material_signals) + 0.03 * len(evidence)), 3),
            "summary": summary,
            "risk_factors": risk_factors,
            "claims": claims,
            "recommended_actions": actions,
            "data_gaps": data_gaps,
        }

    # --- verifier ---------------------------------------------------------

    def _verify(self, request: LLMRequest) -> dict[str, Any]:
        claims: list[dict[str, Any]] = request.context.get("claims", []) or []
        verifications = []
        for claim in claims:
            evidence_texts = [item.get("content", "") for item in claim.get("evidence", [])]
            status, confidence, reason, revision = classify_with_rules(
                claim.get("text", ""),
                evidence_texts,
                has_valid_evidence=bool(claim.get("has_valid_evidence", bool(evidence_texts))),
                claim_type=claim.get("claim_type"),
            )
            verifications.append(
                {
                    "claim_key": claim.get("key", ""),
                    "status": status.value,
                    "confidence": confidence,
                    "reasoning": reason,
                    "suggested_revision": revision,
                    "checked_references": [item.get("reference", "") for item in claim.get("evidence", [])],
                }
            )
        return {"verifications": verifications}

    # --- reporter ---------------------------------------------------------

    def _report(self, request: LLMRequest) -> dict[str, Any]:
        context = request.context
        objective: str = context.get("objective", "")
        accounts: list[dict[str, Any]] = context.get("accounts", []) or []
        stats: dict[str, Any] = context.get("stats", {}) or {}
        window = context.get("parameters", {}).get("renewal_window_days", 90)

        if not accounts:
            return {
                "title": "Churn risk investigation — no accounts above threshold",
                "executive_summary": (
                    "No account in the selected population crossed the configured risk threshold "
                    f"of {stats.get('risk_threshold', 'n/a')} during this run. "
                    f"{stats.get('candidates', 0)} candidate account(s) renewing within {window} days "
                    "were screened with the deterministic risk model and none required investigation. "
                    "No retention action is recommended at this time."
                ),
                "portfolio_observations": [
                    f"{stats.get('candidates', 0)} accounts were screened; "
                    f"{stats.get('investigated', 0)} met the investigation threshold."
                ],
                "unresolved_uncertainties": [
                    "A low screening result reflects the available data only; accounts with sparse "
                    "usage or survey history can be under-scored."
                ],
                "account_narratives": {},
            }

        ranked = sorted(accounts, key=lambda a: a.get("risk_score", 0), reverse=True)
        top = ranked[0]
        narratives: dict[str, str] = {}
        for account in ranked:
            conclusions = account.get("verified_conclusions", [])
            indicators = account.get("quantitative_indicators", [])
            parts = [
                f"{account.get('company_name')} scores {account.get('risk_score')}/100 "
                f"({account.get('risk_level')}) with a renewal on {account.get('renewal_date') or 'an unknown date'}."
            ]
            if indicators:
                parts.append("Verified indicators: " + "; ".join(indicators[:3]) + ".")
            if conclusions:
                parts.append("Verified conclusions: " + " ".join(conclusions[:3]))
            excluded = account.get("excluded_conclusions", [])
            if excluded:
                parts.append(f"{len(excluded)} conclusion(s) were excluded because the evidence did not support them.")
            if account.get("data_gaps"):
                parts.append("Open data gaps: " + "; ".join(account["data_gaps"][:3]) + ".")
            narratives[account["customer_external_id"]] = " ".join(parts)

        summary = (
            f"{len(ranked)} account(s) renewing within {window} days were investigated against the "
            f'objective: "{_shorten(objective, 160)}". '
            f"{top.get('company_name')} carries the highest verified churn risk at "
            f"{top.get('risk_score')}/100 ({top.get('risk_level')}). "
            f"{stats.get('supported_claims', 0)} of {stats.get('total_claims', 0)} material claims were "
            "verified as supported by evidence; "
            f"{stats.get('rejected_claims', 0)} were rejected or rewritten and are excluded from the "
            "conclusions below. Total ARR represented by the investigated accounts is "
            f"${stats.get('investigated_acv', 0):,.0f}."
        )
        return {
            "title": f"Churn risk investigation — {len(ranked)} account(s) renewing within {window} days",
            "executive_summary": summary,
            "portfolio_observations": _portfolio_observations(ranked, stats),
            "unresolved_uncertainties": _uncertainties(ranked),
            "account_narratives": narratives,
        }


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _severity_to_level(severity: float) -> RiskLevel:
    if severity >= 0.75:
        return RiskLevel.CRITICAL
    if severity >= 0.5:
        return RiskLevel.HIGH
    if severity >= 0.25:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _score_to_level(score: float) -> RiskLevel:
    settings = get_settings()
    if score >= settings.risk_threshold_critical:
        return RiskLevel.CRITICAL
    if score >= settings.risk_threshold_high:
        return RiskLevel.HIGH
    if score >= settings.risk_threshold_medium:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _metric_reference(signal: dict[str, Any], evidence: list[dict[str, Any]]) -> str | None:
    """Find the metric evidence row this signal was computed from."""
    for item in evidence:
        metadata = item.get("metadata") or {}
        if metadata.get("signal_key") == signal.get("key"):
            return item.get("reference")
    return None


def _references_for_signal(signal: dict[str, Any], evidence: list[dict[str, Any]]) -> list[str]:
    reference = _metric_reference(signal, evidence)
    return [reference] if reference else []


def _metric_claim_text(company: str, signal: dict[str, Any], value: Any) -> str:
    detail = signal.get("detail") or ""
    if detail:
        # Keep the deterministic wording: the evidence row contains this text
        # verbatim, so the verifier's numeric check passes by construction.
        return f"{company}: {detail}"
    unit = signal.get("unit", "")
    return f"{company} shows {signal['label'].lower()} at {value}{unit}."


def _observed_claim_text(company: str, sentence: str) -> str:
    sentence = sentence.strip().rstrip(".")
    lowered = sentence.lower()
    if any(hedge in lowered for hedge in HEDGE_PHRASES):
        return f"Account records state that {company} {_to_third_person(sentence)}."
    return f'Account records state: "{sentence}."'


def _to_third_person(sentence: str) -> str:
    text = re.sub(r"^\s*(we|they|the customer|the team)\s+", "", sentence, flags=re.IGNORECASE)
    text = re.sub(r"^\s*are\s+", "is ", text, flags=re.IGNORECASE)
    return text[0].lower() + text[1:] if text else sentence


def _salient_sentence(content: str) -> str | None:
    """Pick the sentence most likely to matter to a churn investigation."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", content) if len(s.strip()) > 25]
    if not sentences:
        return None
    scored = sorted(
        sentences,
        key=lambda s: sum(1 for marker in _SENTIMENT_NEGATIVE + _INTENT_PHRASES if marker in s.lower()),
        reverse=True,
    )
    best = scored[0]
    return best if len(best) <= 300 else best[:297] + "..."


def _find_intent_evidence(evidence: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in evidence:
        content = (item.get("content") or "").lower()
        if any(phrase in content for phrase in _INTENT_PHRASES) and any(hedge in content for hedge in HEDGE_PHRASES):
            return item
    return None


def _recommended_actions(score: float, signals: list[dict[str, Any]], metrics: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = [
        {
            "action_type": ActionType.ASSIGN_OWNER.value,
            "description": "Assign a named retention owner and open a save plan for this account.",
            "rationale": "Accounts above the investigation threshold need a single accountable owner.",
            "priority": 1,
        }
    ]
    keys = {signal["key"] for signal in signals}
    if "active_user_decline" in keys or "usage_decline" in keys:
        actions.append(
            {
                "action_type": ActionType.SCHEDULE_CUSTOMER_CALL.value,
                "description": "Schedule a workflow review call with the account's day-to-day owners.",
                "rationale": "Usage decline needs a conversation about what changed in their workflow.",
                "priority": 1,
            }
        )
    if "support_pressure" in keys or "csat" in keys:
        actions.append(
            {
                "action_type": ActionType.ESCALATE_TO_EXECUTIVE.value,
                "description": "Escalate the open support backlog to the support director for a resolution plan.",
                "rationale": "Unresolved high-priority tickets are a live churn driver.",
                "priority": 2,
            }
        )
    if "payment_delinquency" in keys:
        actions.append(
            {
                "action_type": ActionType.SEND_CUSTOMER_EMAIL.value,
                "description": "Email the billing contact to resolve the overdue invoice before renewal.",
                "rationale": "Overdue invoices at renewal often signal an internal budget decision.",
                "priority": 2,
            }
        )
    if score >= 70 and (metrics.get("monthly_recurring_revenue") or 0) >= 5000:
        actions.append(
            {
                "action_type": ActionType.OFFER_DISCOUNT.value,
                "description": "Prepare a retention offer for executive review before the renewal conversation.",
                "rationale": "High-value account at critical risk; a commercial lever may be required.",
                "priority": 3,
            }
        )
    actions.append(
        {
            "action_type": ActionType.MONITOR_USAGE.value,
            "description": "Re-check active users and ticket volume 7 days after the first intervention.",
            "rationale": "Confirms whether the intervention changed behaviour before renewal.",
            "priority": 4,
        }
    )
    return actions[:6]


def _investigation_summary(
    company: str,
    score: float,
    level: RiskLevel,
    signals: list[dict[str, Any]],
    metrics: dict[str, Any],
    data_gaps: list[str],
) -> str:
    drivers = ", ".join(signal["label"].lower() for signal in signals[:3]) or "no material signals"
    renewal = metrics.get("days_to_renewal")
    renewal_text = f"The renewal is {renewal} day(s) away. " if isinstance(renewal, int) else ""
    gap_text = f" Confidence is limited by missing data: {'; '.join(data_gaps[:2])}." if data_gaps else ""
    return (
        f"{company} scores {score:.1f}/100 on the deterministic churn-risk model ({level.value}). "
        f"The dominant drivers are {drivers}. {renewal_text}"
        "Each material statement below is tied to a specific evidence record and was verified "
        f"independently before being reported.{gap_text}"
    )


def _portfolio_observations(accounts: list[dict[str, Any]], stats: dict[str, Any]) -> list[str]:
    observations = [
        f"{stats.get('candidates', 0)} account(s) were screened and {len(accounts)} crossed the "
        f"investigation threshold of {stats.get('risk_threshold', 'n/a')}.",
    ]
    levels: dict[str, int] = {}
    for account in accounts:
        levels[account.get("risk_level", "UNKNOWN")] = levels.get(account.get("risk_level", "UNKNOWN"), 0) + 1
    if levels:
        observations.append(
            "Risk distribution: " + ", ".join(f"{count} {level}" for level, count in sorted(levels.items())) + "."
        )
    shared: dict[str, int] = {}
    for account in accounts:
        for indicator in account.get("driver_keys", []):
            shared[indicator] = shared.get(indicator, 0) + 1
    repeated = [key for key, count in shared.items() if count > 1]
    if repeated:
        observations.append("Drivers shared across multiple accounts: " + ", ".join(sorted(repeated)) + ".")
    if stats.get("rejected_claims"):
        observations.append(
            f"{stats['rejected_claims']} claim(s) were rejected or rewritten during verification and "
            "are excluded from the conclusions."
        )
    return observations


def _uncertainties(accounts: list[dict[str, Any]]) -> list[str]:
    uncertainties: list[str] = []
    for account in accounts:
        for gap in account.get("data_gaps", [])[:2]:
            uncertainties.append(f"{account.get('company_name')}: {gap}")
    for account in accounts:
        for excluded in account.get("excluded_conclusions", [])[:1]:
            uncertainties.append(f"{account.get('company_name')}: an investigator conclusion was excluded — {excluded}")
    if not uncertainties:
        uncertainties.append(
            "No material data gaps were detected, but the dataset is synthetic and evidence coverage varies by account."
        )
    return uncertainties[:12]


def _shorten(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def stable_hash(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)
