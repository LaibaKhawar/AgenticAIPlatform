"""Deterministic sensitive-action policy.

This module is the only authority on whether a proposed action needs human
approval. It is plain application logic with no model in the loop, because the
failure mode of asking an LLM "does this need approval?" is that it eventually
says no.

An LLM chooses *which* action type to recommend. The policy decides what happens
next, and the orchestrator will not advance a run past the approval stage while
any request is pending.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

from app.models.enums import SENSITIVE_ACTIONS, ActionType, WorkflowMode


@dataclass(frozen=True)
class ApprovalDecision:
    required: bool
    reason: str


def requires_approval(action_type: ActionType, *, workflow_mode: WorkflowMode = WorkflowMode.STANDARD) -> bool:
    return decide(action_type, workflow_mode=workflow_mode).required


def decide(action_type: ActionType, *, workflow_mode: WorkflowMode = WorkflowMode.STANDARD) -> ApprovalDecision:
    """Why an action is (or is not) gated — the reason is stored on the record."""
    if workflow_mode is WorkflowMode.READ_ONLY:
        # In read-only mode no write action should have been proposed at all;
        # gate everything rather than letting one through.
        return ApprovalDecision(
            required=True,
            reason="Run is in READ_ONLY mode: no action may be taken without explicit review.",
        )
    if workflow_mode is WorkflowMode.REVIEW_ALL:
        return ApprovalDecision(
            required=True, reason="Run is in REVIEW_ALL mode: every recommended action is reviewed."
        )
    if action_type in SENSITIVE_ACTIONS:
        return ApprovalDecision(
            required=True,
            reason=(
                f"{action_type.value} has an external or commercial side effect "
                "(customer contact, discount, CRM or subscription change) and requires approval."
            ),
        )
    return ApprovalDecision(
        required=False,
        reason=f"{action_type.value} is an internal, read-only action and executes without approval.",
    )


def is_executable_without_approval(action_type: ActionType, workflow_mode: WorkflowMode) -> bool:
    return not requires_approval(action_type, workflow_mode=workflow_mode)


def approval_idempotency_key(*, customer_id: uuid.UUID | None, action_type: ActionType, description: str) -> str:
    """Stable key so a retried task cannot open a second identical approval.

    The description is hashed rather than stored raw so a long recommendation
    still fits the column and small whitespace differences do not create a new
    request.
    """
    normalised = " ".join(description.lower().split())
    digest = hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:16]
    return f"{customer_id or 'portfolio'}:{action_type.value}:{digest}"


def sensitive_action_catalogue() -> list[dict[str, object]]:
    """Surfaced by the API so the UI can explain the policy to a reviewer."""
    return [
        {
            "action_type": action.value,
            "requires_approval": action in SENSITIVE_ACTIONS,
            "reason": decide(action).reason,
        }
        for action in ActionType
    ]
