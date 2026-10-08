"""Plan validation and dependency scheduling."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.errors import PlanValidationError
from app.models.enums import AgentType, TaskStatus
from app.orchestration.dag import (
    DagNode,
    blocked_tasks,
    find_cycle,
    plan_to_nodes,
    ready_tasks,
    topological_order,
    validate_plan,
)
from app.schemas.agent import ExecutionPlan, TaskDefinition

pytestmark = pytest.mark.unit


def task(task_id: str, agent: str = "data", deps: list[str] | None = None) -> dict:
    return {
        "id": task_id,
        "agent": agent,
        "description": f"do {task_id}",
        "dependencies": deps or [],
    }


CANONICAL = [
    task("select_candidates", "data"),
    task("screen_risk", "risk", ["select_candidates"]),
    task("investigate_accounts", "investigator", ["screen_risk"]),
    task("verify_claims", "verifier", ["investigate_accounts"]),
    task("generate_report", "reporter", ["verify_claims"]),
    task("request_approvals", "policy", ["generate_report"]),
    task("finalize", "system", ["request_approvals"]),
]


def plan(tasks: list[dict]) -> ExecutionPlan:
    return ExecutionPlan(objective="investigate churn risk", tasks=tasks)


# --------------------------------------------------------------------------- #
# Valid plans
# --------------------------------------------------------------------------- #


def test_canonical_plan_validates() -> None:
    validated = validate_plan(plan(CANONICAL))
    assert len(validated.tasks) == 7
    assert validated.tasks[0].agent is AgentType.DATA


def test_optional_task_may_be_omitted() -> None:
    reduced = [t for t in CANONICAL if t["id"] != "request_approvals"]
    reduced = [
        {**t, "dependencies": [d for d in t["dependencies"] if d != "request_approvals"] or ["generate_report"]}
        if t["id"] == "finalize"
        else t
        for t in reduced
    ]
    validate_plan(plan(reduced))


# --------------------------------------------------------------------------- #
# Rejections
# --------------------------------------------------------------------------- #


def test_duplicate_task_ids_are_rejected_by_the_schema() -> None:
    with pytest.raises(ValidationError, match="duplicate task ids"):
        plan([*CANONICAL, task("screen_risk", "risk", ["select_candidates"])])


def test_dependency_on_an_undefined_task_is_rejected_by_the_schema() -> None:
    with pytest.raises(ValidationError, match="unknown task"):
        plan([task("select_candidates", "data", ["does_not_exist"])])


def test_self_dependency_is_rejected() -> None:
    with pytest.raises(ValidationError, match="depends on itself"):
        plan([task("select_candidates", "data", ["select_candidates"])])


def test_unknown_agent_is_rejected_by_the_schema() -> None:
    with pytest.raises(ValidationError):
        plan([task("select_candidates", "quantum_oracle")])


def test_planner_agent_is_not_an_executable_task_agent() -> None:
    """The planner cannot schedule itself as a workflow task."""
    tasks = [{**t, "agent": "planner"} if t["id"] == "select_candidates" else t for t in CANONICAL]
    with pytest.raises(PlanValidationError, match="does not have"):
        validate_plan(plan(tasks))


def test_invented_task_id_is_rejected() -> None:
    tasks = [*CANONICAL, task("call_the_customer", "data", ["screen_risk"])]
    with pytest.raises(PlanValidationError) as error:
        validate_plan(plan(tasks))
    assert "no executor" in str(error.value)
    assert "call_the_customer" in str(error.value)


def test_missing_required_task_is_rejected() -> None:
    tasks = [t for t in CANONICAL if t["id"] != "verify_claims"]
    tasks = [
        {**t, "dependencies": ["investigate_accounts"]} if t["id"] == "generate_report" else t
        for t in tasks
    ]
    with pytest.raises(PlanValidationError, match="omits required task"):
        validate_plan(plan(tasks))


def test_circular_dependency_is_detected() -> None:
    """Built directly, bypassing the schema, to prove the cycle check works."""
    tasks = [
        TaskDefinition(id="select_candidates", agent=AgentType.DATA, description="select candidates", dependencies=["finalize"]),
        TaskDefinition(id="screen_risk", agent=AgentType.RISK, description="screen risk", dependencies=["select_candidates"]),
        TaskDefinition(id="verify_claims", agent=AgentType.VERIFIER, description="verify claims", dependencies=["screen_risk"]),
        TaskDefinition(id="generate_report", agent=AgentType.REPORTER, description="generate report", dependencies=["verify_claims"]),
        TaskDefinition(id="finalize", agent=AgentType.SYSTEM, description="finalize the run", dependencies=["generate_report"]),
    ]
    built = ExecutionPlan.model_construct(objective="o", tasks=tasks)
    with pytest.raises(PlanValidationError, match="cycle"):
        validate_plan(built)


def test_plan_task_limit_is_enforced() -> None:
    with pytest.raises(PlanValidationError, match="exceeds the limit"):
        validate_plan(plan(CANONICAL), max_tasks=3)


def test_plan_validation_reports_every_problem_at_once() -> None:
    tasks = [*CANONICAL, task("teleport_customer", "data", ["screen_risk"])]
    with pytest.raises(PlanValidationError) as error:
        validate_plan(plan(tasks), max_tasks=4)
    problems = error.value.details["problems"]
    assert len(problems) >= 2


# --------------------------------------------------------------------------- #
# Graph algorithms
# --------------------------------------------------------------------------- #


def test_find_cycle_returns_the_path() -> None:
    cycle = find_cycle({"a": ["b"], "b": ["c"], "c": ["a"]})
    assert cycle is not None
    assert cycle[0] == cycle[-1]


def test_find_cycle_returns_none_for_a_dag() -> None:
    assert find_cycle({"a": [], "b": ["a"], "c": ["a", "b"]}) is None


def test_find_cycle_detects_self_loops() -> None:
    assert find_cycle({"a": ["a"]}) is not None


def test_topological_order_respects_dependencies() -> None:
    order = topological_order({"c": ["b"], "b": ["a"], "a": []})
    assert order == ["a", "b", "c"]


def test_topological_order_is_deterministic_for_parallel_branches() -> None:
    graph = {"root": [], "x": ["root"], "y": ["root"], "join": ["x", "y"]}
    assert topological_order(graph) == topological_order(graph)
    assert topological_order(graph)[-1] == "join"


def test_topological_order_rejects_a_cycle() -> None:
    with pytest.raises(PlanValidationError):
        topological_order({"a": ["b"], "b": ["a"]})


# --------------------------------------------------------------------------- #
# Readiness
# --------------------------------------------------------------------------- #


def test_ready_tasks_requires_all_dependencies_completed() -> None:
    nodes = [DagNode("a", ()), DagNode("b", ("a",)), DagNode("c", ("a", "b"))]
    statuses = {"a": TaskStatus.COMPLETED, "b": TaskStatus.PENDING, "c": TaskStatus.PENDING}
    assert ready_tasks(nodes, statuses) == ["b"]


def test_running_tasks_are_not_ready_again() -> None:
    nodes = [DagNode("a", ())]
    assert ready_tasks(nodes, {"a": TaskStatus.RUNNING}) == []


def test_retrying_tasks_are_eligible_for_dispatch() -> None:
    nodes = [DagNode("a", ())]
    assert ready_tasks(nodes, {"a": TaskStatus.RETRYING}) == ["a"]


def test_a_failed_dependency_blocks_a_normal_task() -> None:
    nodes = [DagNode("a", ()), DagNode("b", ("a",))]
    statuses = {"a": TaskStatus.FAILED, "b": TaskStatus.PENDING}
    assert ready_tasks(nodes, statuses) == []
    assert blocked_tasks(nodes, statuses) == ["b"]


def test_blocked_propagates_through_the_graph() -> None:
    nodes = [DagNode("a", ()), DagNode("b", ("a",)), DagNode("c", ("b",))]
    statuses = {"a": TaskStatus.FAILED, "b": TaskStatus.PENDING, "c": TaskStatus.PENDING}
    assert sorted(blocked_tasks(nodes, statuses)) == ["b", "c"]


def test_tolerant_aggregator_runs_when_only_some_branches_failed() -> None:
    """One customer's investigation failing must not strand the whole run."""
    nodes = [
        DagNode("screen", ()),
        DagNode("investigate:A", ("screen",)),
        DagNode("investigate:B", ("screen",)),
        DagNode("aggregate", ("investigate:A", "investigate:B")),
    ]
    statuses = {
        "screen": TaskStatus.COMPLETED,
        "investigate:A": TaskStatus.COMPLETED,
        "investigate:B": TaskStatus.FAILED,
        "aggregate": TaskStatus.PENDING,
    }
    assert ready_tasks(nodes, statuses, tolerant_keys={"aggregate"}) == ["aggregate"]
    assert blocked_tasks(nodes, statuses, tolerant_keys={"aggregate"}) == []


def test_tolerant_aggregator_is_blocked_when_every_branch_failed() -> None:
    nodes = [
        DagNode("screen", ()),
        DagNode("investigate:A", ("screen",)),
        DagNode("aggregate", ("investigate:A",)),
    ]
    statuses = {
        "screen": TaskStatus.COMPLETED,
        "investigate:A": TaskStatus.FAILED,
        "aggregate": TaskStatus.PENDING,
    }
    assert ready_tasks(nodes, statuses, tolerant_keys={"aggregate"}) == []
    assert blocked_tasks(nodes, statuses, tolerant_keys={"aggregate"}) == ["aggregate"]


def test_downstream_of_a_tolerant_aggregator_is_not_blocked() -> None:
    nodes = [
        DagNode("investigate:A", ()),
        DagNode("aggregate", ("investigate:A",)),
        DagNode("report", ("aggregate",)),
    ]
    statuses = {
        "investigate:A": TaskStatus.FAILED,
        "aggregate": TaskStatus.COMPLETED,
        "report": TaskStatus.PENDING,
    }
    assert blocked_tasks(nodes, statuses, tolerant_keys={"aggregate"}) == []
    assert ready_tasks(nodes, statuses, tolerant_keys={"aggregate"}) == ["report"]


def test_no_dead_tasks_means_nothing_is_blocked() -> None:
    nodes = [DagNode("a", ()), DagNode("b", ("a",))]
    assert blocked_tasks(nodes, {"a": TaskStatus.COMPLETED, "b": TaskStatus.PENDING}) == []


def test_plan_to_nodes_preserves_dependencies() -> None:
    nodes = plan_to_nodes(validate_plan(plan(CANONICAL)).tasks)
    by_key = {node.key: node for node in nodes}
    assert by_key["verify_claims"].dependencies == ("investigate_accounts",)
