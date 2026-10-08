"""Deterministic claim verification: the hallucination-mitigation core."""

from __future__ import annotations

import pytest

from app.analytics.claim_rules import (
    RuleVerdict,
    classify_with_rules,
    evaluate_claim,
    extract_numbers,
    hedge_claim,
    is_hedged,
    lexical_overlap,
    soften_claim,
)
from app.models.enums import ClaimStatus, ClaimType

pytestmark = pytest.mark.unit

EVALUATING = "We are evaluating alternative platforms ahead of the renewal. Competitor X reached out."
ESCALATION = "Three tickets are open past our target resolution time and the team is frustrated."


# --------------------------------------------------------------------------- #
# The headline requirement
# --------------------------------------------------------------------------- #


def test_evaluating_alternatives_supports_an_evaluation_claim() -> None:
    status, confidence, reason, revision = classify_with_rules(
        "The customer is evaluating alternative platforms.", [EVALUATING]
    )
    assert status is ClaimStatus.SUPPORTED
    assert confidence > 0.5
    assert revision is None
    assert reason


def test_evaluating_alternatives_does_not_support_a_cancellation_decision() -> None:
    """The single most important guardrail in this system."""
    status, _confidence, reason, revision = classify_with_rules(
        "The customer has decided to cancel.", [EVALUATING]
    )
    assert status is ClaimStatus.CONTRADICTED
    assert "overstates" in reason
    assert revision is not None
    assert "decided to cancel" not in revision.lower()


@pytest.mark.parametrize(
    "claim",
    [
        "Acme has decided to cancel their contract.",
        "The account has churned.",
        "The customer will not renew.",
        "They have already moved to Competitor X.",
        "The customer confirmed cancellation last week.",
        "This account has terminated the contract.",
    ],
)
def test_certainty_upgrades_are_rejected_against_exploratory_evidence(claim: str) -> None:
    result = evaluate_claim(claim, [EVALUATING])
    assert result.is_veto
    assert result.status in {ClaimStatus.CONTRADICTED, ClaimStatus.UNSUPPORTED}
    assert result.matched_certainty is not None


def test_a_certainty_claim_is_supported_when_the_evidence_actually_says_it() -> None:
    evidence = "The customer has decided to cancel and gave formal notice on Monday."
    result = evaluate_claim("The customer has decided to cancel.", [evidence])
    assert not result.is_veto
    assert result.verdict is RuleVerdict.PASS


def test_rule_veto_cannot_be_satisfied_by_unrelated_hedged_evidence() -> None:
    result = evaluate_claim("The customer has churned.", ["Usage increased by 12% this month."])
    assert result.is_veto
    assert result.status is ClaimStatus.UNSUPPORTED


# --------------------------------------------------------------------------- #
# Evidence existence
# --------------------------------------------------------------------------- #


def test_claim_with_no_evidence_is_unsupported() -> None:
    result = evaluate_claim("Usage fell sharply.", [])
    assert result.status is ClaimStatus.UNSUPPORTED
    assert result.is_veto


def test_claim_whose_evidence_failed_validation_is_unsupported() -> None:
    """A hallucinated evidence id must be rejected without consulting a model."""
    result = evaluate_claim("Usage fell sharply.", ["some text"], has_valid_evidence=False)
    assert result.status is ClaimStatus.UNSUPPORTED
    assert "no valid evidence" in result.reason.lower()


# --------------------------------------------------------------------------- #
# Numbers
# --------------------------------------------------------------------------- #


def test_unmatched_numbers_downgrade_the_claim() -> None:
    result = evaluate_claim(
        "Active users fell 91% over the period.",
        ["Average daily active users changed -47.5% (81.5 -> 42.8)."],
    )
    assert result.status is ClaimStatus.PARTIALLY_SUPPORTED
    assert "91%" in result.unmatched_numbers


def test_matching_numbers_pass() -> None:
    result = evaluate_claim(
        "Average daily active users changed -47.5%.",
        ["Average daily active users changed -47.5% (81.5 -> 42.8)."],
    )
    assert result.verdict is RuleVerdict.PASS


def test_small_rounding_differences_are_tolerated() -> None:
    result = evaluate_claim(
        "CSAT averaged 2.04 across rated tickets.",
        ["Average CSAT 2.05 across 11 rated ticket(s)."],
    )
    assert result.verdict is RuleVerdict.PASS


def test_extract_numbers_handles_percentages_and_thousands() -> None:
    assert extract_numbers("usage fell 47.5% from 1,200 to 630") == ["47.5%", "1200", "630"]


# --------------------------------------------------------------------------- #
# Inferences are judged differently
# --------------------------------------------------------------------------- #


def test_hedged_inference_is_supported_despite_low_term_overlap() -> None:
    """An interpretation legitimately uses words the source never contains."""
    claim = "The account appears to be at elevated churn risk, driven primarily by declining engagement."
    overlap = lexical_overlap(claim, ESCALATION)
    assert overlap < 0.2, "precondition: this claim shares almost no vocabulary with its evidence"

    result = evaluate_claim(claim, [ESCALATION], claim_type=ClaimType.INFERENCE)
    assert result.verdict is RuleVerdict.PASS

    status, _confidence, _reason, _revision = classify_with_rules(
        claim, [ESCALATION], claim_type=ClaimType.INFERENCE
    )
    assert status is ClaimStatus.SUPPORTED


def test_unhedged_inference_is_downgraded_and_given_a_hedged_revision() -> None:
    """An inference stated as flat fact is reworded, not accepted."""
    claim = "Support failures are the primary driver of this account's churn exposure."
    result = evaluate_claim(claim, [ESCALATION], claim_type=ClaimType.INFERENCE)
    assert result.status is ClaimStatus.PARTIALLY_SUPPORTED
    assert result.suggested_revision is not None
    assert is_hedged(result.suggested_revision)


def test_inference_asserting_a_future_certainty_is_vetoed() -> None:
    """"will churn" is a certainty phrase, so it is rejected outright rather
    than softened into an acceptable inference."""
    result = evaluate_claim(
        "The account will churn because engagement collapsed.",
        [ESCALATION],
        claim_type=ClaimType.INFERENCE,
    )
    assert result.is_veto
    assert result.matched_certainty == "will churn"
    assert result.suggested_revision is not None
    assert "will churn" not in result.suggested_revision


def test_an_inference_may_not_upgrade_certainty_either() -> None:
    result = evaluate_claim(
        "The customer has decided to cancel, so churn is certain.",
        [EVALUATING],
        claim_type=ClaimType.INFERENCE,
    )
    assert result.is_veto


def test_observed_fact_with_low_overlap_is_only_partially_supported() -> None:
    claim = "Procurement has blocked the renewal for budget reasons."
    result = evaluate_claim(claim, [ESCALATION], claim_type=ClaimType.OBSERVED_FACT)
    assert result.status is ClaimStatus.PARTIALLY_SUPPORTED
    assert result.suggested_revision is not None


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def test_lexical_overlap_bounds() -> None:
    assert lexical_overlap("reporting failures", "reporting failures") == pytest.approx(1.0)
    assert lexical_overlap("reporting failures", "completely different words here") == pytest.approx(0.0)
    assert lexical_overlap("", "anything") == pytest.approx(0.0)


def test_soften_claim_rewrites_the_overreach() -> None:
    softened = soften_claim("Acme Corp has decided to cancel their contract.", "has decided to cancel")
    assert "evaluating alternatives" in softened
    assert "decided to cancel" not in softened


def test_soften_claim_leaves_unknown_phrases_alone() -> None:
    assert soften_claim("Some claim.", "not-a-known-phrase") == "Some claim."


def test_hedge_claim_marks_the_statement_as_an_interpretation() -> None:
    hedged = hedge_claim("Usage is collapsing")
    assert hedged.startswith("The evidence indicates")
    assert is_hedged(hedged)


def test_hedge_claim_is_idempotent_on_already_qualified_text() -> None:
    once = hedge_claim("Usage is collapsing")
    assert hedge_claim(once) == once


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("The account may churn", True),
        ("This appears to be a risk", True),
        ("Usage is at risk", True),
        ("Usage fell 40%", False),
    ],
)
def test_is_hedged(text: str, expected: bool) -> None:
    assert is_hedged(text) is expected


# --------------------------------------------------------------------------- #
# Negation
# --------------------------------------------------------------------------- #

NEGATED_RENEWAL_NOTE = (
    "Renewal date is approximately one month out. Status: no renewal commitment, competitive "
    "evaluation in progress. Nothing in the record indicates that the customer has cancelled or "
    "given notice."
)


def test_a_negated_certainty_phrase_in_evidence_does_not_license_the_claim() -> None:
    """Regression: a note recording the *absence* of a cancellation was being
    read as evidence that the cancellation happened, which silently disabled the
    system's strongest guardrail."""
    result = evaluate_claim("The customer has decided to cancel.", [NEGATED_RENEWAL_NOTE])
    assert result.is_veto
    assert result.status is ClaimStatus.CONTRADICTED
    assert result.suggested_revision is not None


def test_negation_is_scoped_to_its_own_sentence() -> None:
    """A negation in a previous sentence must not neutralise a real assertion."""
    evidence = "There is no outstanding invoice. The customer has decided to cancel, effective March."
    result = evaluate_claim("The customer has decided to cancel.", [evidence])
    assert not result.is_veto, "an explicit cancellation in its own sentence does support the claim"


@pytest.mark.parametrize(
    "evidence",
    [
        "They have not cancelled their contract.",
        "The customer has yet to cancel.",
        "No evidence that they have churned.",
        "The account denies that it will not renew.",
        "They are far from having decided to cancel.",
    ],
)
def test_various_negation_forms_are_recognised(evidence: str) -> None:
    result = evaluate_claim("The customer has decided to cancel.", [evidence])
    assert result.is_veto, f"negated evidence should not license the claim: {evidence}"


def test_an_unambiguous_cancellation_still_supports_the_claim() -> None:
    evidence = "The customer has decided to cancel and submitted formal written notice on Monday."
    result = evaluate_claim("The customer has decided to cancel.", [evidence])
    assert not result.is_veto
