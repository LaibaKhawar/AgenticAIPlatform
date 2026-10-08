"""Deterministic claim-verification rules.

These rules run *before* (and independently of) the verifier LLM. They exist
because a language model asked "is this claim supported?" will sometimes say yes
to a claim whose evidence it never saw, and because the single most damaging
hallucination in this domain is a certainty upgrade:

    evidence:  "We are evaluating alternative platforms."
    supported: "The customer is evaluating alternatives."
    NOT ok:    "The customer has decided to cancel."

The rules below can *veto* a claim (hard verdict) and can also produce an
advisory signal the verifier agent must take into account. They are used in
three places: the verifier's programmatic pre-check, the deterministic fake LLM
(so the test suite exercises real judgement logic), and the unit tests.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from app.models.enums import ClaimStatus, ClaimType

# Phrases asserting a settled, irreversible decision or completed event.
CERTAINTY_PHRASES: tuple[str, ...] = (
    "has decided to cancel",
    "have decided to cancel",
    "decided to cancel",
    "has cancelled",
    "have cancelled",
    "has churned",
    "will churn",
    "is churning",
    "has terminated",
    "terminated the contract",
    "confirmed cancellation",
    "confirmed they are cancelling",
    "will not renew",
    "will definitely",
    "has already moved",
    "have already moved",
    "has switched to",
    "have switched to",
    "has signed with",
    "have signed with",
    "is leaving",
    "are leaving",
    "gave notice",
    "given notice",
)

# Phrases that mark an evidence statement as exploratory / uncommitted.
HEDGE_PHRASES: tuple[str, ...] = (
    "evaluating",
    "evaluate",
    "considering",
    "consider",
    "exploring",
    "explore",
    "may ",
    "might",
    "could",
    "possible",
    "potentially",
    "looking at",
    "comparing",
    "benchmarking",
    "asked about",
    "requested pricing",
    "weighing",
    "reviewing options",
    "under review",
    "evaluation",
    "in progress",
    "no decision",
    "undecided",
    "no commitment",
    "not committed",
)

# Hedges that make a *claim* an interpretation rather than an assertion of fact.
CLAIM_HEDGES: tuple[str, ...] = (
    "may",
    "might",
    "could",
    "appears",
    "suggests",
    "indicates",
    "likely",
    "risk of",
    "at risk",
    "potential",
    "possible",
    "signals",
)

_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "of",
        "to",
        "in",
        "on",
        "for",
        "with",
        "at",
        "by",
        "from",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "their",
        "there",
        "has",
        "have",
        "had",
        "do",
        "does",
        "did",
        "not",
        "no",
        "as",
        "we",
        "they",
        "you",
        "i",
        "he",
        "she",
        "them",
        "our",
        "your",
        "his",
        "her",
        "about",
        "into",
        "over",
        "under",
        "than",
        "then",
        "so",
        "such",
        "very",
        "more",
        "most",
        "less",
        "least",
        "can",
        "will",
        "would",
        "should",
        "could",
        "may",
        "might",
        "also",
        "both",
        "each",
        "other",
        "any",
        "all",
        "some",
        "which",
        "who",
        "whom",
        "whose",
        "if",
        "because",
        "while",
        "during",
        "before",
        "after",
        "above",
        "below",
        "between",
        "through",
        "per",
    ]
)

_NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)?%?")
_TOKEN_RE = re.compile(r"[a-z0-9$%.-]+")


class RuleVerdict(StrEnum):
    VETO_CONTRADICTED = "VETO_CONTRADICTED"
    VETO_UNSUPPORTED = "VETO_UNSUPPORTED"
    ADVISE_PARTIAL = "ADVISE_PARTIAL"
    PASS = "PASS"


@dataclass(frozen=True)
class RuleResult:
    verdict: RuleVerdict
    status: ClaimStatus | None
    reason: str
    overlap: float
    matched_certainty: str | None = None
    unmatched_numbers: tuple[str, ...] = ()
    suggested_revision: str | None = None

    @property
    def is_veto(self) -> bool:
        return self.verdict in {RuleVerdict.VETO_CONTRADICTED, RuleVerdict.VETO_UNSUPPORTED}


def tokenize(text: str) -> set[str]:
    return {token for token in _TOKEN_RE.findall(text.lower()) if token not in _STOPWORDS and len(token) > 2}


def lexical_overlap(claim_text: str, evidence_text: str) -> float:
    """Fraction of the claim's content words that appear in the evidence."""
    claim_tokens = tokenize(claim_text)
    if not claim_tokens:
        return 0.0
    evidence_tokens = tokenize(evidence_text)
    return round(len(claim_tokens & evidence_tokens) / len(claim_tokens), 4)


def extract_numbers(text: str) -> list[str]:
    return [match.group(0).replace(",", "") for match in _NUMBER_RE.finditer(text)]


def _numbers_present(claim_text: str, evidence_text: str) -> list[str]:
    """Numbers asserted in the claim that no evidence item contains.

    A 1% tolerance is allowed so "declined 47.6%" is backed by "declined 48%".
    """
    evidence_values: list[float] = []
    for raw in extract_numbers(evidence_text):
        try:
            evidence_values.append(float(raw.rstrip("%")))
        except ValueError:
            continue

    missing: list[str] = []
    for raw in extract_numbers(claim_text):
        try:
            value = float(raw.rstrip("%"))
        except ValueError:
            continue
        tolerance = max(0.5, abs(value) * 0.01)
        if not any(abs(value - candidate) <= tolerance for candidate in evidence_values):
            missing.append(raw)
    return missing


# Cues that negate a following phrase. Real account notes very often record the
# *absence* of an event — "nothing in the record indicates they have cancelled" —
# and reading that as evidence that they cancelled inverts the meaning of the
# document. This matters most on the evidence side: a negated certainty phrase
# must not be mistaken for the source asserting certainty, or the strongest
# guardrail in the system silently stops firing.
NEGATION_CUES: tuple[str, ...] = (
    "nothing",
    "no indication",
    "no evidence",
    "no sign",
    "not ",
    "n't",
    "never",
    "neither",
    "nor ",
    "denies",
    "denied",
    "without",
    "unlikely",
    "has yet to",
    "have yet to",
    "yet to",
    "far from",
    "rather than",
    "no decision",
    "undecided",
)

# How far back to look for a negation cue, in characters.
_NEGATION_WINDOW = 90


def _is_negated(lowered: str, index: int) -> bool:
    window = lowered[max(0, index - _NEGATION_WINDOW) : index]
    # Stop at a sentence boundary: a negation in the previous sentence does not
    # negate this one.
    for boundary in (". ", "! ", "? ", "\n"):
        position = window.rfind(boundary)
        if position != -1:
            window = window[position + len(boundary) :]
    return any(cue in window for cue in NEGATION_CUES)


def _find_phrase(text: str, phrases: tuple[str, ...], *, skip_negated: bool = False) -> str | None:
    """First matching phrase, or ``None``.

    With ``skip_negated=True`` an occurrence whose clause contains a negation
    cue is ignored, so "they have not cancelled" is not read as "cancelled".
    """
    lowered = f" {text.lower()} "
    for phrase in phrases:
        start = 0
        while True:
            index = lowered.find(phrase, start)
            if index == -1:
                break
            if not (skip_negated and _is_negated(lowered, index)):
                return phrase.strip()
            start = index + len(phrase)
    return None


def soften_claim(claim_text: str, certainty_phrase: str) -> str:
    """Rewrite a certainty overreach into something the evidence can support."""
    replacements = {
        "has decided to cancel": "is evaluating alternatives",
        "have decided to cancel": "are evaluating alternatives",
        "decided to cancel": "is evaluating alternatives",
        "has cancelled": "is at risk of cancelling",
        "have cancelled": "are at risk of cancelling",
        "has churned": "is at elevated churn risk",
        "will churn": "may churn",
        "is churning": "shows churn-risk behaviour",
        "has terminated": "may not renew",
        "terminated the contract": "may not renew the contract",
        "confirmed cancellation": "raised the possibility of cancelling",
        "confirmed they are cancelling": "raised the possibility of cancelling",
        "will not renew": "may not renew",
        "will definitely": "may",
        "has already moved": "is evaluating moving",
        "have already moved": "are evaluating moving",
        "has switched to": "is evaluating",
        "have switched to": "are evaluating",
        "has signed with": "is evaluating",
        "have signed with": "are evaluating",
        "is leaving": "is at risk of leaving",
        "are leaving": "are at risk of leaving",
        "gave notice": "raised the possibility of cancelling",
        "given notice": "raised the possibility of cancelling",
    }
    softened = replacements.get(certainty_phrase)
    if softened is None:
        return claim_text
    pattern = re.compile(re.escape(certainty_phrase), re.IGNORECASE)
    return pattern.sub(softened, claim_text)


def hedge_claim(claim_text: str) -> str:
    """Turn an unhedged statement into an explicit interpretation.

    Used when a claim's direction is supported but its wording is stronger than
    the evidence. A qualified statement a reader can act on is more useful than
    silently dropping the finding.
    """
    text = claim_text.strip().rstrip(".")
    lowered = text.lower()
    if lowered.startswith(("the evidence", "evidence indicates", "account records")):
        return f"{text}."
    return f"The evidence indicates, but does not prove, that {text[0].lower() + text[1:]}."


def is_hedged(claim_text: str) -> bool:
    return _find_phrase(claim_text, CLAIM_HEDGES) is not None


def evaluate_claim(
    claim_text: str,
    evidence_texts: list[str],
    *,
    has_valid_evidence: bool = True,
    claim_type: ClaimType | str | None = None,
) -> RuleResult:
    """Apply the deterministic rules to one claim.

    ``has_valid_evidence`` is ``False`` when every cited evidence reference
    failed programmatic validation (a hallucinated ``EV-9``), which is an
    immediate, non-negotiable rejection.

    ``claim_type`` matters because the rules are asking different questions of
    different claims. "Active users fell 47.5%" must match the evidence almost
    word for word. "The account appears to be at elevated churn risk, driven by
    that decline" is an *interpretation* — it legitimately uses words the source
    documents never contain, so judging it on term overlap would reject exactly
    the reasoning the product exists to produce. Inferences are therefore held
    to a different standard: they must be hedged, they must cite real evidence,
    and they must not upgrade certainty — but they are not required to echo the
    source's vocabulary.
    """
    inference = _as_claim_type(claim_type) is ClaimType.INFERENCE

    if not has_valid_evidence or not evidence_texts:
        return RuleResult(
            verdict=RuleVerdict.VETO_UNSUPPORTED,
            status=ClaimStatus.UNSUPPORTED,
            reason=("No valid evidence is attached to this claim, so it cannot be stated as fact."),
            overlap=0.0,
        )

    combined = "\n".join(evidence_texts)
    overlap = max(lexical_overlap(claim_text, text) for text in evidence_texts)
    combined_overlap = lexical_overlap(claim_text, combined)
    overlap = max(overlap, combined_overlap)

    certainty = _find_phrase(claim_text, CERTAINTY_PHRASES)
    if certainty:
        # Negated occurrences do not count: a note saying they have *not*
        # cancelled is not the source asserting that they cancelled.
        evidence_certainty = _find_phrase(combined, CERTAINTY_PHRASES, skip_negated=True)
        evidence_hedge = _find_phrase(combined, HEDGE_PHRASES)
        # Did the source say the opposite outright ("nothing indicates they
        # have cancelled")? That is a contradiction, not simply silence.
        explicitly_denied = (
            evidence_certainty is None and _find_phrase(combined, CERTAINTY_PHRASES) is not None
        )
        if evidence_certainty is None:
            status = (
                ClaimStatus.CONTRADICTED
                if (evidence_hedge or explicitly_denied)
                else ClaimStatus.UNSUPPORTED
            )
            if explicitly_denied:
                detail = "explicitly records that this has not happened"
            elif evidence_hedge:
                detail = f"expresses an exploratory position ({evidence_hedge})"
            else:
                detail = "does not state this"
            reason = (
                f'The claim asserts "{certainty}" as settled fact. The evidence '
                f"{detail}, so the claim overstates what the source says."
            )
            return RuleResult(
                verdict=(
                    RuleVerdict.VETO_CONTRADICTED
                    if status is ClaimStatus.CONTRADICTED
                    else RuleVerdict.VETO_UNSUPPORTED
                ),
                status=status,
                reason=reason,
                overlap=overlap,
                matched_certainty=certainty,
                suggested_revision=soften_claim(claim_text, certainty),
            )

    missing_numbers = _numbers_present(claim_text, combined)
    if missing_numbers:
        return RuleResult(
            verdict=RuleVerdict.ADVISE_PARTIAL,
            status=ClaimStatus.PARTIALLY_SUPPORTED,
            reason=("The claim states figures that do not appear in the cited evidence: " + ", ".join(missing_numbers)),
            overlap=overlap,
            unmatched_numbers=tuple(missing_numbers),
        )

    if inference:
        # An inference stands or falls on being honestly framed, not on
        # repeating the source's words.
        if not is_hedged(claim_text):
            return RuleResult(
                verdict=RuleVerdict.ADVISE_PARTIAL,
                status=ClaimStatus.PARTIALLY_SUPPORTED,
                reason=(
                    "This is an inference but it is worded as a statement of fact. It must be "
                    "framed as an interpretation of the cited evidence."
                ),
                overlap=overlap,
                suggested_revision=hedge_claim(claim_text),
            )
        return RuleResult(
            verdict=RuleVerdict.PASS,
            status=None,
            reason=(
                f"Hedged inference drawn from {len(evidence_texts)} cited evidence record(s) "
                f"(term overlap {overlap:.0%}; an interpretation is not expected to echo the source)."
            ),
            overlap=overlap,
        )

    if overlap < 0.2:
        return RuleResult(
            verdict=RuleVerdict.ADVISE_PARTIAL,
            status=ClaimStatus.PARTIALLY_SUPPORTED,
            reason=(
                f"Only {overlap:.0%} of the claim's terms appear in the cited evidence; the link "
                "between claim and source is weak."
            ),
            overlap=overlap,
            suggested_revision=hedge_claim(claim_text),
        )

    return RuleResult(
        verdict=RuleVerdict.PASS,
        status=None,
        reason=f"Claim terms overlap the cited evidence ({overlap:.0%}).",
        overlap=overlap,
    )


def _as_claim_type(value: ClaimType | str | None) -> ClaimType | None:
    if value is None:
        return None
    if isinstance(value, ClaimType):
        return value
    try:
        return ClaimType(value)
    except ValueError:
        return None


def classify_with_rules(
    claim_text: str,
    evidence_texts: list[str],
    *,
    has_valid_evidence: bool = True,
    claim_type: ClaimType | str | None = None,
) -> tuple[ClaimStatus, float, str, str | None]:
    """Full deterministic verdict: ``(status, confidence, reason, revision)``.

    Used by the fake LLM verifier so the deterministic test suite exercises real
    verification logic rather than a canned answer.
    """
    result = evaluate_claim(
        claim_text, evidence_texts, has_valid_evidence=has_valid_evidence, claim_type=claim_type
    )
    if result.status is not None:
        confidence = 0.9 if result.is_veto else 0.55
        return result.status, confidence, result.reason, result.suggested_revision

    if result.overlap >= 0.5 or is_hedged(claim_text):
        return (
            ClaimStatus.SUPPORTED,
            round(min(0.95, 0.6 + result.overlap / 2), 3),
            result.reason,
            None,
        )
    return (
        ClaimStatus.PARTIALLY_SUPPORTED,
        round(0.4 + result.overlap / 2, 3),
        result.reason + " The evidence supports the direction but not the full wording.",
        hedge_claim(claim_text),
    )
