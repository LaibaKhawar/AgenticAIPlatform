"""Typed model boundaries.

Every LLM → application boundary in this system is a Pydantic model. Malformed
output is never silently accepted: the client retries with the validation error
appended to the prompt and then fails the task (see
:class:`app.core.errors.StructuredOutputError`).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import (
    ActionType,
    AgentType,
    ClaimStatus,
    ClaimType,
    RiskLevel,
    WorkflowType,
)

Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
Score100 = Annotated[float, Field(ge=0.0, le=100.0)]


class StrictModel(BaseModel):
    """Reject unknown fields so a drifting prompt surfaces as a hard error."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# --------------------------------------------------------------------------- #
# Planning
# --------------------------------------------------------------------------- #


class TaskDefinition(StrictModel):
    id: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9][a-z0-9_:\-]*$")
    agent: AgentType
    description: str = Field(min_length=3, max_length=500)
    stage: str = Field(default="execution", max_length=60)
    dependencies: list[str] = Field(default_factory=list, max_length=40)
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("dependencies")
    @classmethod
    def _unique_dependencies(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("dependencies must be unique")
        return value


class ExecutionPlan(StrictModel):
    objective: str = Field(min_length=1, max_length=8000)
    workflow_type: WorkflowType = WorkflowType.CHURN_INVESTIGATION
    reasoning: str = Field(default="", max_length=4000)
    tasks: list[TaskDefinition] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _structural_checks(self) -> ExecutionPlan:
        """Cheap structural checks. Registry/DAG validation lives in
        :mod:`app.orchestration.dag` because it needs the agent registry."""
        ids = [task.id for task in self.tasks]
        duplicates = {task_id for task_id in ids if ids.count(task_id) > 1}
        if duplicates:
            raise ValueError(f"duplicate task ids: {sorted(duplicates)}")
        known = set(ids)
        for task in self.tasks:
            unknown = [dep for dep in task.dependencies if dep not in known]
            if unknown:
                raise ValueError(f"task '{task.id}' depends on unknown task(s): {unknown}")
            if task.id in task.dependencies:
                raise ValueError(f"task '{task.id}' depends on itself")
        return self


# --------------------------------------------------------------------------- #
# Evidence and signals
# --------------------------------------------------------------------------- #


class EvidenceItem(StrictModel):
    """A retrieved, attributable piece of evidence.

    ``content`` is untrusted customer data. It is passed to models inside an
    explicitly delimited, labelled block and never as instructions.
    """

    reference: str = Field(min_length=2, max_length=32)
    evidence_id: str | None = None
    source_type: str
    source_id: str
    customer_id: str | None = None
    title: str = ""
    content: str
    source_date: date | None = None
    relevance_score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RiskSignalModel(StrictModel):
    key: str
    label: str
    value: float | None = None
    unit: str = ""
    severity: Confidence = 0.0
    weight: float = 0.0
    contribution: float = 0.0
    detail: str = ""


class RiskFactor(StrictModel):
    factor: str = Field(min_length=3, max_length=200)
    explanation: str = Field(min_length=3, max_length=1200)
    severity: RiskLevel = RiskLevel.MEDIUM
    evidence_references: list[str] = Field(default_factory=list, max_length=12)


class ClaimDraft(StrictModel):
    """A material claim produced by the investigator, pending verification."""

    key: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=5, max_length=1000)
    claim_type: ClaimType
    confidence: Confidence = 0.5
    evidence_references: list[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def _factual_claims_need_evidence(self) -> ClaimDraft:
        """Observed facts and calculated metrics must cite something.

        Inferences may stand on the other claims, but they must still be typed
        as inferences — which is what stops "we think" becoming "it is".
        """
        if self.claim_type in {ClaimType.OBSERVED_FACT, ClaimType.CALCULATED_METRIC} and not self.evidence_references:
            raise ValueError(f"claim '{self.key}' is typed {self.claim_type.value} but cites no evidence")
        return self


class RecommendedAction(StrictModel):
    action_type: ActionType
    description: str = Field(min_length=3, max_length=600)
    rationale: str = Field(default="", max_length=1200)
    priority: Annotated[int, Field(ge=1, le=5)] = 3
    # requires_approval is deliberately absent: it is decided by deterministic
    # policy (app.policy.approvals), never by the model.


class InvestigationResult(StrictModel):
    """The investigator agent's typed output for a single customer."""

    customer_external_id: str
    risk_score: Score100
    risk_level: RiskLevel
    confidence: Confidence
    summary: str = Field(min_length=10, max_length=4000)
    risk_factors: list[RiskFactor] = Field(default_factory=list, max_length=12)
    claims: list[ClaimDraft] = Field(default_factory=list, max_length=25)
    recommended_actions: list[RecommendedAction] = Field(default_factory=list, max_length=10)
    data_gaps: list[str] = Field(default_factory=list, max_length=12)


# --------------------------------------------------------------------------- #
# Verification
# --------------------------------------------------------------------------- #


class ClaimVerification(StrictModel):
    claim_key: str
    status: ClaimStatus
    confidence: Confidence
    reasoning: str = Field(min_length=3, max_length=2000)
    suggested_revision: str | None = Field(default=None, max_length=1000)
    # References the verifier actually judged against (after programmatic
    # validation removed anything hallucinated).
    checked_references: list[str] = Field(default_factory=list, max_length=12)


class VerificationBatch(StrictModel):
    verifications: list[ClaimVerification] = Field(default_factory=list, max_length=100)


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


class ReportAccountSection(StrictModel):
    customer_external_id: str
    company_name: str
    risk_score: Score100
    risk_level: RiskLevel
    confidence: Confidence
    renewal_date: date | None = None
    monthly_recurring_revenue: float | None = None
    quantitative_indicators: list[str] = Field(default_factory=list, max_length=20)
    qualitative_evidence: list[str] = Field(default_factory=list, max_length=20)
    verified_conclusions: list[str] = Field(default_factory=list, max_length=20)
    # Findings the evidence supports in direction but not in wording. Reported
    # with an explicit qualifier rather than dropped, so a reader sees the
    # signal and its limits instead of nothing at all.
    qualified_findings: list[str] = Field(default_factory=list, max_length=20)
    excluded_conclusions: list[str] = Field(default_factory=list, max_length=20)
    recommended_actions: list[RecommendedAction] = Field(default_factory=list, max_length=10)
    evidence_references: list[str] = Field(default_factory=list, max_length=40)
    uncertainties: list[str] = Field(default_factory=list, max_length=12)


class FinalReport(StrictModel):
    title: str = Field(min_length=3, max_length=300)
    executive_summary: str = Field(min_length=10, max_length=6000)
    accounts: list[ReportAccountSection] = Field(default_factory=list, max_length=50)
    portfolio_observations: list[str] = Field(default_factory=list, max_length=20)
    unresolved_uncertainties: list[str] = Field(default_factory=list, max_length=20)
    methodology_notes: list[str] = Field(default_factory=list, max_length=20)


# --------------------------------------------------------------------------- #
# Narrative-only model outputs (the LLM writes prose, the app owns the numbers)
# --------------------------------------------------------------------------- #


class ReportNarrative(StrictModel):
    """What the reporter LLM is allowed to produce.

    Ranked accounts, scores and evidence references are assembled by the
    application from verified rows, so the model cannot reorder or invent them.
    """

    title: str = Field(min_length=3, max_length=300)
    executive_summary: str = Field(min_length=10, max_length=6000)
    portfolio_observations: list[str] = Field(default_factory=list, max_length=20)
    unresolved_uncertainties: list[str] = Field(default_factory=list, max_length=20)
    account_narratives: dict[str, str] = Field(default_factory=dict)
