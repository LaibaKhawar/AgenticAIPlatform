"""Structured-output schemas and deterministic planner parameter resolution."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agents.planner import resolve_parameters
from app.core.config import get_settings
from app.models.enums import ActionType, ClaimStatus, ClaimType, RiskLevel
from app.schemas.agent import (
    ClaimDraft,
    ClaimVerification,
    EvidenceItem,
    InvestigationResult,
    RecommendedAction,
    ReportNarrative,
    TaskDefinition,
    VerificationBatch,
)

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Claim typing rules
# --------------------------------------------------------------------------- #


def test_observed_fact_without_evidence_is_rejected() -> None:
    """The schema itself refuses an uncited fact — before any verifier runs."""
    with pytest.raises(ValidationError, match="cites no evidence"):
        ClaimDraft(
            key="c1",
            text="The customer is evaluating alternatives.",
            claim_type=ClaimType.OBSERVED_FACT,
            evidence_references=[],
        )


def test_calculated_metric_without_evidence_is_rejected() -> None:
    with pytest.raises(ValidationError, match="cites no evidence"):
        ClaimDraft(
            key="c2",
            text="Active users fell 47%.",
            claim_type=ClaimType.CALCULATED_METRIC,
            evidence_references=[],
        )


def test_inference_may_stand_without_a_direct_citation() -> None:
    claim = ClaimDraft(
        key="c3",
        text="The account appears to be at elevated risk.",
        claim_type=ClaimType.INFERENCE,
        evidence_references=[],
    )
    assert claim.claim_type is ClaimType.INFERENCE


def test_claim_confidence_must_be_a_probability() -> None:
    for bad in (-0.1, 1.5):
        with pytest.raises(ValidationError):
            ClaimDraft(
                key="c",
                text="Active users fell 47%.",
                claim_type=ClaimType.CALCULATED_METRIC,
                confidence=bad,
                evidence_references=["EV-1"],
            )


def test_claim_text_has_a_minimum_and_maximum_length() -> None:
    with pytest.raises(ValidationError):
        ClaimDraft(key="c", text="no", claim_type=ClaimType.INFERENCE)
    with pytest.raises(ValidationError):
        ClaimDraft(key="c", text="x" * 1001, claim_type=ClaimType.INFERENCE)


def test_evidence_reference_count_is_bounded() -> None:
    with pytest.raises(ValidationError):
        ClaimDraft(
            key="c",
            text="Active users fell 47%.",
            claim_type=ClaimType.CALCULATED_METRIC,
            evidence_references=[f"EV-{i}" for i in range(50)],
        )


# --------------------------------------------------------------------------- #
# Unknown fields and enums
# --------------------------------------------------------------------------- #


def test_unknown_fields_are_rejected_so_prompt_drift_is_loud() -> None:
    with pytest.raises(ValidationError):
        RecommendedAction(
            action_type=ActionType.MONITOR_USAGE,
            description="Watch usage",
            # A model inventing its own approval flag must not be silently kept.
            requires_approval=False,
        )


def test_recommended_action_cannot_declare_its_own_approval_requirement() -> None:
    assert "requires_approval" not in RecommendedAction.model_fields


def test_unknown_action_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RecommendedAction(action_type="DELETE_THE_ACCOUNT", description="no")


def test_unknown_risk_level_is_rejected() -> None:
    with pytest.raises(ValidationError):
        InvestigationResult(
            customer_external_id="CUST-1",
            risk_score=50,
            risk_level="EXTREME",
            confidence=0.5,
            summary="a summary long enough to pass validation",
        )


def test_risk_score_is_bounded_to_0_100() -> None:
    for bad in (-1, 101):
        with pytest.raises(ValidationError):
            InvestigationResult(
                customer_external_id="CUST-1",
                risk_score=bad,
                risk_level=RiskLevel.HIGH,
                confidence=0.5,
                summary="a summary long enough to pass validation",
            )


def test_valid_investigation_result_round_trips() -> None:
    result = InvestigationResult(
        customer_external_id="CUST-000001",
        risk_score=92.2,
        risk_level=RiskLevel.CRITICAL,
        confidence=0.81,
        summary="Active users halved and the renewal is a month away.",
        claims=[
            ClaimDraft(
                key="m1",
                text="Active users changed -47.5%.",
                claim_type=ClaimType.CALCULATED_METRIC,
                evidence_references=["EV-1"],
            )
        ],
        recommended_actions=[
            RecommendedAction(action_type=ActionType.ASSIGN_OWNER, description="Assign an owner.")
        ],
        data_gaps=["No NPS response on record."],
    )
    dumped = result.model_dump(mode="json")
    assert InvestigationResult.model_validate(dumped) == result


def test_task_definition_id_pattern_rejects_odd_identifiers() -> None:
    for bad in ("Select Candidates", "select candidates", "../etc/passwd", ""):
        with pytest.raises(ValidationError):
            TaskDefinition(id=bad, agent="data", description="a description")


def test_task_definition_rejects_duplicate_dependencies() -> None:
    with pytest.raises(ValidationError, match="unique"):
        TaskDefinition(id="screen_risk", agent="risk", description="screen", dependencies=["a", "a"])


def test_verification_batch_accepts_all_statuses() -> None:
    batch = VerificationBatch(
        verifications=[
            ClaimVerification(claim_key=f"c{i}", status=status, confidence=0.5, reasoning="because")
            for i, status in enumerate(ClaimStatus)
        ]
    )
    assert len(batch.verifications) == len(list(ClaimStatus))


def test_evidence_item_keeps_full_attribution() -> None:
    item = EvidenceItem(
        reference="EV-1",
        source_type="DOCUMENT_CHUNK",
        source_id="chunk:abc",
        content="We are evaluating alternatives.",
        relevance_score=0.42,
        metadata={"document_id": "d1"},
    )
    assert item.reference == "EV-1"
    assert item.metadata["document_id"] == "d1"
    assert item.relevance_score == pytest.approx(0.42)


def test_report_narrative_requires_a_substantive_summary() -> None:
    with pytest.raises(ValidationError):
        ReportNarrative(title="Report", executive_summary="short")


# --------------------------------------------------------------------------- #
# Planner parameter resolution (deterministic regex, not an LLM call)
# --------------------------------------------------------------------------- #


def test_explicit_controls_always_win_over_the_objective_text() -> None:
    resolved = resolve_parameters(
        "Look at SMB customers renewing within 30 days and find the top 3.",
        {"renewal_window_days": 120, "max_accounts": 7, "account_tier": "ENTERPRISE"},
    )
    assert resolved["renewal_window_days"] == 120
    assert resolved["max_accounts"] == 7
    assert resolved["account_tier"] == "ENTERPRISE"


@pytest.mark.parametrize(
    ("objective", "expected"),
    [
        ("customers renewing within the next 90 days", 90),
        ("accounts renewing in 45 days", 45),
        ("renewals within 6 weeks for our customers", 42),
        ("churn risk for customers renewing within 3 months", 90),
        ("customer renewals in the next 2 quarters", 180),
    ],
)
def test_renewal_window_is_parsed_from_the_objective(objective: str, expected: int) -> None:
    assert resolve_parameters(objective, {})["renewal_window_days"] == expected


def test_renewal_window_defaults_to_90_days() -> None:
    assert resolve_parameters("Find churn risk in our customer base.", {})["renewal_window_days"] == 90


@pytest.mark.parametrize(
    ("objective", "expected"),
    [
        ("identify the five accounts at highest risk of churn", 5),
        ("find the top 3 at-risk customers", 3),
        ("show the top 10 churn risks for customers", 10),
    ],
)
def test_account_count_is_parsed(objective: str, expected: int) -> None:
    assert resolve_parameters(objective, {})["max_accounts"] == expected


def test_account_count_defaults_to_five() -> None:
    assert resolve_parameters("Investigate churn risk across customers.", {})["max_accounts"] == 5


def test_account_count_is_clamped_to_the_configured_ceiling() -> None:
    ceiling = get_settings().max_investigation_candidates
    assert resolve_parameters("x", {"max_accounts": 9999})["max_accounts"] == ceiling


def test_renewal_window_is_clamped() -> None:
    assert resolve_parameters("x", {"renewal_window_days": 100_000})["renewal_window_days"] == 400


@pytest.mark.parametrize(
    ("objective", "tier"),
    [
        ("Analyze enterprise customers at risk", "ENTERPRISE"),
        ("look at mid-market accounts", "MID_MARKET"),
        ("our SMB customers", "SMB"),
        ("startup accounts renewing soon", "STARTUP"),
        ("all customers renewing soon", None),
    ],
)
def test_tier_is_parsed_from_the_objective(objective: str, tier: str | None) -> None:
    assert resolve_parameters(objective, {})["account_tier"] == tier


def test_resolved_parameters_always_include_the_risk_threshold() -> None:
    resolved = resolve_parameters("customer churn risk", {})
    assert resolved["risk_threshold"] == get_settings().risk_investigation_threshold
    assert resolved["workflow_mode"] == "STANDARD"
