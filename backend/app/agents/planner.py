"""Planner agent.

Turns a natural-language business objective into a validated task DAG. The
planner is deliberately constrained: it may only compose tasks the orchestrator
can actually execute, using agents the platform actually has. Anything else is
rejected by :func:`app.orchestration.dag.validate_plan` before persistence.

The planner also extracts the structured parameters the deterministic stages
need (renewal window, account tier, how many accounts to investigate). Those are
read from the operator's explicit controls first; the objective text is only
used to fill gaps, and the result is clamped to configured limits.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.agents.base import AgentConfig, AgentRunContext, BaseAgent, system_prompt
from app.core.config import get_settings
from app.core.errors import UnsupportedObjectiveError
from app.core.logging import get_logger
from app.llm.client import CallRecord
from app.models.enums import AgentType, WorkflowType
from app.orchestration.dag import EXECUTABLE_TASK_KEYS, SUPPORTED_AGENTS, validate_plan
from app.schemas.agent import ExecutionPlan

logger = get_logger(__name__)

# An objective must plausibly be about the customer-retention domain this
# workflow implements. We refuse clearly out-of-scope work rather than
# producing a confident churn report for "summarise our AWS bill".
DOMAIN_TERMS = (
    "churn",
    "renew",
    "retention",
    "customer",
    "account",
    "subscription",
    "at risk",
    "at-risk",
    "cancel",
    "downgrade",
    "expansion",
    "arr",
    "mrr",
    "nps",
    "csat",
    "revenue",
    "upsell",
    "contract",
    "health",
)


@dataclass(frozen=True)
class PlannerOutput:
    plan: ExecutionPlan
    parameters: dict[str, Any]
    call_record: CallRecord | None


class PlannerAgent(BaseAgent):
    config = AgentConfig(
        agent_type=AgentType.PLANNER,
        role=(
            "Decomposes a business objective into a validated, dependency-ordered task graph "
            "using only the platform's real capabilities."
        ),
        allowed_tools=(),
        timeout_seconds=60.0,
        max_retries=2,
    )

    def output_schema_name(self) -> str:
        return ExecutionPlan.__name__

    def plan(
        self,
        context: AgentRunContext,
        *,
        objective: str,
        parameters: dict[str, Any] | None = None,
    ) -> PlannerOutput:
        settings = get_settings()
        objective = objective.strip()
        if len(objective) > settings.max_objective_chars:
            raise UnsupportedObjectiveError(f"objective exceeds the {settings.max_objective_chars} character limit")
        if not _looks_in_domain(objective):
            raise UnsupportedObjectiveError(
                "This objective does not appear to describe a customer-retention investigation. "
                "Veriflow V1 implements the B2B SaaS churn-investigation workflow; rephrase the "
                "objective in terms of customers, accounts, renewals or churn risk.",
                details={"supported_workflow": WorkflowType.CHURN_INVESTIGATION.value},
            )

        resolved = resolve_parameters(objective, parameters or {})

        with self.traced(context, "planner"):
            plan, record = self.call_model(
                context,
                operation="plan",
                system_prompt=_system_prompt(),
                user_prompt=_user_prompt(objective, resolved),
                output_model=ExecutionPlan,
                payload={"objective": objective, "parameters": resolved},
            )
            validate_plan(plan)
            logger.info(
                "execution plan validated",
                extra={"task_count": len(plan.tasks), "parameters": resolved},
            )
        return PlannerOutput(plan=plan, parameters=resolved, call_record=record)


def _looks_in_domain(objective: str) -> bool:
    lowered = objective.lower()
    return any(term in lowered for term in DOMAIN_TERMS)


def ensure_supported_objective(objective: str) -> None:
    """Reject an objective this workflow cannot honestly serve.

    Called at run-creation time (so the operator gets an immediate 422) and
    again by the planner (so a run created by any other path is still guarded).
    """
    settings = get_settings()
    if len(objective) > settings.max_objective_chars:
        raise UnsupportedObjectiveError(
            f"The objective exceeds the {settings.max_objective_chars} character limit."
        )
    if not _looks_in_domain(objective):
        raise UnsupportedObjectiveError(
            "This objective does not appear to describe a customer-retention investigation. "
            f"{settings.product_name} V1 implements the B2B SaaS churn-investigation workflow; "
            "rephrase the objective in terms of customers, accounts, renewals or churn risk.",
            details={"supported_workflow": WorkflowType.CHURN_INVESTIGATION.value},
        )


def _system_prompt() -> str:
    return system_prompt(
        "Your role: PLANNER.\n\n"
        "Produce an ExecutionPlan for a B2B SaaS customer-churn investigation.\n\n"
        f"You may ONLY use these agents: {sorted(a.value for a in SUPPORTED_AGENTS)}.\n"
        f"You may ONLY use these task ids: {sorted(EXECUTABLE_TASK_KEYS)}.\n"
        "Every task id must be one of those exact strings — they map to real executors. "
        "Do not invent tasks, agents, tools or capabilities. Do not create cycles. "
        "Dependencies must reference task ids present in the same plan.\n\n"
        "The workflow must always: select candidates deterministically, screen them with the "
        "deterministic risk model, investigate the selected accounts, verify the resulting claims "
        "independently, generate a report from verified material, apply the approval policy, and "
        "finalise.\n\n"
        "Per-account investigation tasks are expanded by the platform at runtime; plan the single "
        "'investigate_accounts' task rather than one task per customer."
    )


def _user_prompt(objective: str, parameters: dict[str, Any]) -> str:
    tier = parameters.get("account_tier") or "any tier"
    return (
        f"Business objective:\n{objective}\n\n"
        "Resolved structured parameters (already validated by the platform — use these, do not "
        "re-derive them):\n"
        f"- renewal window: {parameters['renewal_window_days']} days\n"
        f"- account tier: {tier}\n"
        f"- maximum accounts to investigate: {parameters['max_accounts']}\n"
        f"- workflow mode: {parameters['workflow_mode']}\n\n"
        "Return the ExecutionPlan."
    )


# --------------------------------------------------------------------------- #
# Parameter resolution
# --------------------------------------------------------------------------- #

_DAYS_RE = re.compile(r"(?:next|within|in)\s+(?:the\s+)?(\d{1,3})\s*(day|week|month|quarter)", re.I)
_COUNT_RE = re.compile(
    r"(?:top|highest|first|identify(?:\s+the)?)\s+(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)\b",
    re.I,
)
_WORD_NUMBERS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}
_TIER_PATTERNS = (
    (re.compile(r"\benterprise\b", re.I), "ENTERPRISE"),
    (re.compile(r"\bmid[- ]?market\b", re.I), "MID_MARKET"),
    (re.compile(r"\bsmb\b|\bsmall business\b", re.I), "SMB"),
    (re.compile(r"\bstartup\b", re.I), "STARTUP"),
)


def resolve_parameters(objective: str, explicit: dict[str, Any]) -> dict[str, Any]:
    """Merge operator controls with hints parsed from the objective text.

    Explicit controls always win. Parsing is deterministic regex over the
    objective — not an LLM call — because "90 days" is not a judgement call.
    """
    settings = get_settings()

    window = explicit.get("renewal_window_days")
    if window is None:
        window = _parse_window(objective) or 90
    window = max(1, min(int(window), 400))

    max_accounts = explicit.get("max_accounts")
    if max_accounts is None:
        max_accounts = _parse_count(objective) or 5
    max_accounts = max(1, min(int(max_accounts), settings.max_investigation_candidates))

    tier = explicit.get("account_tier")
    if tier is None:
        tier = _parse_tier(objective)

    return {
        "renewal_window_days": window,
        "max_accounts": max_accounts,
        "account_tier": tier,
        "workflow_mode": explicit.get("workflow_mode", "STANDARD"),
        "risk_threshold": explicit.get("risk_threshold", settings.risk_investigation_threshold),
    }


def _parse_window(objective: str) -> int | None:
    match = _DAYS_RE.search(objective)
    if not match:
        return None
    value = int(match.group(1))
    unit = match.group(2).lower()
    multiplier = {"day": 1, "week": 7, "month": 30, "quarter": 90}[unit]
    return value * multiplier


def _parse_count(objective: str) -> int | None:
    match = _COUNT_RE.search(objective)
    if not match:
        return None
    token = match.group(1).lower()
    return _WORD_NUMBERS.get(token, int(token) if token.isdigit() else None)


def _parse_tier(objective: str) -> str | None:
    for pattern, tier in _TIER_PATTERNS:
        if pattern.search(objective):
            return tier
    return None
