"""Approval policy, tool registry permissions and input validation."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from pydantic import BaseModel

from app.core.errors import ToolInputError, ToolNotFoundError, ToolPermissionError
from app.models.enums import SENSITIVE_ACTIONS, ActionType, ToolAccess, WorkflowMode
from app.policy.approvals import (
    approval_idempotency_key,
    decide,
    is_executable_without_approval,
    requires_approval,
    sensitive_action_catalogue,
)
from app.tools import customer_tools as _tools  # noqa: F401 - registers the tools
from app.tools.registry import (
    REGISTRY,
    RetryPolicy,
    ToolContext,
    ToolInvoker,
    ToolRegistry,
    ToolSpec,
)

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Approval policy
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "action",
    [
        ActionType.SEND_CUSTOMER_EMAIL,
        ActionType.OFFER_DISCOUNT,
        ActionType.UPDATE_CRM_RECORD,
        ActionType.CHANGE_SUBSCRIPTION,
        ActionType.ESCALATE_TO_EXECUTIVE,
        ActionType.SCHEDULE_CUSTOMER_CALL,
    ],
)
def test_externally_visible_actions_require_approval(action: ActionType) -> None:
    assert requires_approval(action) is True
    assert action.is_sensitive is True
    assert decide(action).reason


@pytest.mark.parametrize(
    "action",
    [
        ActionType.INTERNAL_REVIEW,
        ActionType.SCHEDULE_INTERNAL_MEETING,
        ActionType.MONITOR_USAGE,
        ActionType.PREPARE_BRIEFING,
        ActionType.ASSIGN_OWNER,
    ],
)
def test_internal_actions_do_not_require_approval(action: ActionType) -> None:
    assert requires_approval(action) is False
    assert is_executable_without_approval(action, WorkflowMode.STANDARD) is True


def test_every_action_type_has_an_explicit_policy_decision() -> None:
    """A new action type must not silently default to "no approval needed"."""
    catalogue = {entry["action_type"] for entry in sensitive_action_catalogue()}
    assert catalogue == {action.value for action in ActionType}
    for entry in sensitive_action_catalogue():
        assert entry["reason"]
        assert isinstance(entry["requires_approval"], bool)


def test_review_all_mode_gates_even_internal_actions() -> None:
    assert requires_approval(ActionType.MONITOR_USAGE, workflow_mode=WorkflowMode.REVIEW_ALL) is True
    assert "REVIEW_ALL" in decide(ActionType.MONITOR_USAGE, workflow_mode=WorkflowMode.REVIEW_ALL).reason


def test_read_only_mode_gates_everything() -> None:
    for action in ActionType:
        assert requires_approval(action, workflow_mode=WorkflowMode.READ_ONLY) is True


def test_sensitive_action_set_matches_the_enum_property() -> None:
    assert {action for action in ActionType if action.is_sensitive} == set(SENSITIVE_ACTIONS)


# --------------------------------------------------------------------------- #
# Approval idempotency
# --------------------------------------------------------------------------- #


def test_idempotency_key_is_stable_for_the_same_action() -> None:
    customer = uuid.uuid4()
    first = approval_idempotency_key(
        customer_id=customer, action_type=ActionType.OFFER_DISCOUNT, description="Prepare a 10% retention offer."
    )
    second = approval_idempotency_key(
        customer_id=customer, action_type=ActionType.OFFER_DISCOUNT, description="Prepare a 10% retention offer."
    )
    assert first == second


def test_idempotency_key_ignores_whitespace_and_case() -> None:
    customer = uuid.uuid4()
    assert approval_idempotency_key(
        customer_id=customer, action_type=ActionType.OFFER_DISCOUNT, description="Prepare   a  10% offer."
    ) == approval_idempotency_key(
        customer_id=customer, action_type=ActionType.OFFER_DISCOUNT, description="prepare a 10% OFFER."
    )


def test_idempotency_key_differs_by_customer_action_and_content() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    base = approval_idempotency_key(customer_id=a, action_type=ActionType.OFFER_DISCOUNT, description="x offer")
    assert base != approval_idempotency_key(customer_id=b, action_type=ActionType.OFFER_DISCOUNT, description="x offer")
    assert base != approval_idempotency_key(
        customer_id=a, action_type=ActionType.SEND_CUSTOMER_EMAIL, description="x offer"
    )
    assert base != approval_idempotency_key(customer_id=a, action_type=ActionType.OFFER_DISCOUNT, description="y offer")


def test_idempotency_key_handles_portfolio_level_actions() -> None:
    key = approval_idempotency_key(customer_id=None, action_type=ActionType.PREPARE_BRIEFING, description="brief")
    assert key.startswith("portfolio:")


def test_idempotency_key_fits_the_column() -> None:
    key = approval_idempotency_key(
        customer_id=uuid.uuid4(), action_type=ActionType.SEND_CUSTOMER_EMAIL, description="x" * 5000
    )
    assert len(key) <= 200


# --------------------------------------------------------------------------- #
# Tool registry
# --------------------------------------------------------------------------- #


REQUIRED_TOOLS = {
    "get_customer_profile",
    "get_subscription",
    "get_usage_summary",
    "get_support_summary",
    "get_payment_summary",
    "get_nps_history",
    "find_upcoming_renewals",
    "get_risk_signals",
    "search_customer_documents",
    "get_document",
    "list_customer_documents",
}


def test_all_required_tools_are_registered() -> None:
    assert set(REGISTRY.names()) >= REQUIRED_TOOLS


def test_there_is_no_sql_or_shell_tool() -> None:
    """Agents must not be able to author queries or run commands."""
    forbidden = ("sql", "query_database", "shell", "exec", "bash", "http", "fetch_url", "eval")
    for name in REGISTRY.names():
        assert not any(token in name.lower() for token in forbidden), name


def test_every_tool_declares_a_complete_contract() -> None:
    for spec in REGISTRY.describe_all():
        assert spec["name"]
        assert spec["description"]
        assert spec["access"] in {ToolAccess.READ_ONLY.value, ToolAccess.SENSITIVE_WRITE.value}
        assert spec["timeout_seconds"] > 0
        assert spec["max_attempts"] >= 1
        assert spec["input_schema"]["type"] == "object"
        assert spec["output_schema"]


def test_only_declared_write_tools_are_sensitive() -> None:
    write_tools = {
        spec["name"] for spec in REGISTRY.describe_all() if spec["access"] == ToolAccess.SENSITIVE_WRITE.value
    }
    assert write_tools == {"propose_customer_action"}
    for name in write_tools:
        assert REGISTRY.get(name).requires_approval is True


def test_unknown_tool_lookup_raises() -> None:
    with pytest.raises(ToolNotFoundError):
        REGISTRY.get("delete_all_customers")


def test_duplicate_registration_is_rejected() -> None:
    registry = ToolRegistry()

    class In(BaseModel):
        pass

    class Out(BaseModel):
        pass

    spec = ToolSpec(
        name="dup",
        description="d",
        input_model=In,
        output_model=Out,
        handler=lambda _ctx, _payload: Out(),
        retry_policy=RetryPolicy(),
    )
    registry.register(spec)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(spec)


# --------------------------------------------------------------------------- #
# Tool permission enforcement
# --------------------------------------------------------------------------- #


class EchoIn(BaseModel):
    value: int


class EchoOut(BaseModel):
    doubled: int


def _registry_with_echo() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="echo",
            description="doubles a number",
            input_model=EchoIn,
            output_model=EchoOut,
            handler=lambda _ctx, payload: EchoOut(doubled=payload.value * 2),
        )
    )
    registry.register(
        ToolSpec(
            name="forbidden_write",
            description="a write tool",
            input_model=EchoIn,
            output_model=EchoOut,
            handler=lambda _ctx, payload: EchoOut(doubled=payload.value),
            access=ToolAccess.SENSITIVE_WRITE,
        )
    )
    return registry


def _invoker(allowed: set[str], **kwargs: Any) -> ToolInvoker:
    return ToolInvoker(
        agent_name="tester",
        allowed_tools=allowed,
        context=ToolContext(session=None),
        registry=_registry_with_echo(),
        **kwargs,
    )


def test_allowed_tool_executes_and_is_recorded() -> None:
    invoker = _invoker({"echo"})
    result = invoker.call("echo", {"value": 21})
    assert isinstance(result, EchoOut)
    assert result.doubled == 42
    assert invoker.usage()["total_calls"] == 1
    assert invoker.usage()["by_tool"] == {"echo": 1}


def test_tool_outside_the_allow_list_is_refused() -> None:
    """The permission boundary is code, not a line in a prompt."""
    invoker = _invoker({"echo"})
    with pytest.raises(ToolPermissionError) as error:
        invoker.call("forbidden_write", {"value": 1})
    assert error.value.details["tool"] == "forbidden_write"
    assert invoker.usage()["total_calls"] == 0


def test_invalid_tool_input_is_rejected_before_the_handler_runs() -> None:
    invoker = _invoker({"echo"})
    with pytest.raises(ToolInputError) as error:
        invoker.call("echo", {"value": "not-a-number"})
    assert error.value.details["errors"]
    assert invoker.usage()["total_calls"] == 0


def test_missing_required_field_is_rejected() -> None:
    with pytest.raises(ToolInputError):
        _invoker({"echo"}).call("echo", {})


def test_tool_call_budget_is_enforced() -> None:
    """Bounds an agent so a loop cannot run away."""
    invoker = _invoker({"echo"}, max_calls=3)
    for _ in range(3):
        invoker.call("echo", {"value": 1})
    with pytest.raises(ToolPermissionError, match="budget"):
        invoker.call("echo", {"value": 1})


def test_unknown_tool_is_refused_even_if_allow_listed() -> None:
    with pytest.raises(ToolNotFoundError):
        _invoker({"nope"}).call("nope", {})


def test_investigator_cannot_call_the_write_tool() -> None:
    """The real agent declaration, not a synthetic one."""
    from app.agents import InvestigatorAgent

    agent = InvestigatorAgent()
    assert "propose_customer_action" not in agent.allowed_tools
    for name in agent.allowed_tools:
        assert REGISTRY.get(name).access is ToolAccess.READ_ONLY


def test_verifier_and_reporter_have_no_tools_at_all() -> None:
    from app.agents import ReporterAgent, VerifierAgent

    assert VerifierAgent().allowed_tools == set()
    assert ReporterAgent().allowed_tools == set()


def test_every_agent_only_declares_registered_tools() -> None:
    from app.agents import AGENT_CLASSES

    for agent_class in AGENT_CLASSES.values():
        agent = agent_class()
        for name in agent.allowed_tools:
            assert name in REGISTRY, f"{agent.name} declares unknown tool {name}"
