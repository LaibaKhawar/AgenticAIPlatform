"""Task-graph validation and scheduling primitives.

The planner's output is untrusted structure: it can duplicate ids, reference a
task that does not exist, name an agent the platform does not have, or describe
a cycle. All of that is rejected here, before a single task row is written.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from app.core.config import get_settings
from app.core.errors import PlanValidationError
from app.models.enums import AgentType, TaskStatus
from app.schemas.agent import ExecutionPlan, TaskDefinition

# Agents a plan may reference, and the stage each one belongs to.
SUPPORTED_AGENTS: frozenset[AgentType] = frozenset(
    {
        AgentType.DATA,
        AgentType.RISK,
        AgentType.RETRIEVAL,
        AgentType.INVESTIGATOR,
        AgentType.VERIFIER,
        AgentType.REPORTER,
        AgentType.POLICY,
        AgentType.SYSTEM,
    }
)

# Task ids the orchestrator knows how to execute. A plan may omit optional
# tasks, but it may not invent an id with no executor behind it.
EXECUTABLE_TASK_KEYS: frozenset[str] = frozenset(
    {
        "select_candidates",
        "screen_risk",
        "investigate_accounts",
        "verify_claims",
        "generate_report",
        "request_approvals",
        "finalize",
    }
)

REQUIRED_TASK_KEYS: frozenset[str] = frozenset(
    {"select_candidates", "screen_risk", "verify_claims", "generate_report", "finalize"}
)

# Dynamic per-customer investigation tasks are created at runtime, not by the
# planner. They use this prefix.
INVESTIGATION_TASK_PREFIX = "investigate:"


@dataclass(frozen=True)
class DagNode:
    key: str
    dependencies: tuple[str, ...]


def validate_plan(plan: ExecutionPlan, *, max_tasks: int | None = None) -> ExecutionPlan:
    """Validate a plan against the platform's real capabilities.

    Raises :class:`PlanValidationError` (a permanent error — never retried with
    the same input) listing every problem found, so a failed run tells an
    operator exactly what the model got wrong.
    """
    settings = get_settings()
    limit = max_tasks or settings.max_plan_tasks
    problems: list[str] = []

    if len(plan.tasks) > limit:
        problems.append(f"plan has {len(plan.tasks)} tasks, which exceeds the limit of {limit}")

    ids = [task.id for task in plan.tasks]
    duplicates = sorted({task_id for task_id in ids if ids.count(task_id) > 1})
    if duplicates:
        problems.append(f"duplicate task ids: {duplicates}")

    unknown_agents = sorted({task.agent.value for task in plan.tasks if task.agent not in SUPPORTED_AGENTS})
    if unknown_agents:
        problems.append(
            f"plan references agents this platform does not have: {unknown_agents}; "
            f"available agents are {sorted(a.value for a in SUPPORTED_AGENTS)}"
        )

    unknown_tasks = sorted({task.id for task in plan.tasks if task.id not in EXECUTABLE_TASK_KEYS})
    if unknown_tasks:
        problems.append(
            f"plan invents task(s) with no executor: {unknown_tasks}; "
            f"supported tasks are {sorted(EXECUTABLE_TASK_KEYS)}"
        )

    known = set(ids)
    for task in plan.tasks:
        missing = [dep for dep in task.dependencies if dep not in known]
        if missing:
            problems.append(f"task '{task.id}' depends on undefined task(s): {missing}")
        if task.id in task.dependencies:
            problems.append(f"task '{task.id}' depends on itself")

    missing_required = sorted(REQUIRED_TASK_KEYS - known)
    if missing_required:
        problems.append(f"plan omits required task(s) for this workflow: {missing_required}")

    cycle = find_cycle({task.id: task.dependencies for task in plan.tasks})
    if cycle:
        problems.append(f"plan contains a dependency cycle: {' -> '.join(cycle)}")

    if problems:
        raise PlanValidationError(
            "the generated plan is not executable: " + "; ".join(problems),
            details={"problems": problems, "task_ids": ids},
        )
    return plan


def find_cycle(graph: Mapping[str, Sequence[str]]) -> list[str] | None:
    """Return one cycle as a path, or ``None`` if the graph is acyclic."""
    WHITE, GREY, BLACK = 0, 1, 2
    colour: dict[str, int] = dict.fromkeys(graph, WHITE)
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        colour[node] = GREY
        stack.append(node)
        for dependency in graph.get(node, ()):
            if dependency not in colour:
                continue
            if colour[dependency] == GREY:
                start = stack.index(dependency)
                return [*stack[start:], dependency]
            if colour[dependency] == WHITE:
                found = visit(dependency)
                if found:
                    return found
        colour[node] = BLACK
        stack.pop()
        return None

    for node in graph:
        if colour[node] == WHITE:
            found = visit(node)
            if found:
                return found
    return None


def topological_order(graph: Mapping[str, Sequence[str]]) -> list[str]:
    """Kahn's algorithm. Raises if the graph is cyclic."""
    indegree = dict.fromkeys(graph, 0)
    dependents: dict[str, list[str]] = {node: [] for node in graph}
    for node, dependencies in graph.items():
        for dependency in dependencies:
            if dependency in indegree:
                indegree[node] += 1
                dependents[dependency].append(node)

    queue = deque(sorted(node for node, degree in indegree.items() if degree == 0))
    order: list[str] = []
    while queue:
        node = queue.popleft()
        order.append(node)
        for dependent in sorted(dependents[node]):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                queue.append(dependent)

    if len(order) != len(graph):
        cycle = find_cycle(graph)
        raise PlanValidationError(f"task graph is cyclic: {' -> '.join(cycle) if cycle else 'unknown cycle'}")
    return order


def ready_tasks(
    nodes: Iterable[DagNode],
    statuses: Mapping[str, TaskStatus],
    *,
    tolerant_keys: Iterable[str] = (),
) -> list[str]:
    """Tasks whose dependencies have all completed and that are still pending.

    A task whose dependency failed or was cancelled is *not* ready; the
    orchestrator skips it explicitly (see :func:`blocked_tasks`).

    ``tolerant_keys`` names tasks that aggregate a fan-out and should still run
    when some branches failed — one customer's investigation failing must not
    strand the verification, reporting and approval stages for the others.
    """
    tolerant = set(tolerant_keys)
    dead = {TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.SKIPPED}
    ready: list[str] = []
    for node in nodes:
        status = statuses.get(node.key)
        if status not in {TaskStatus.PENDING, TaskStatus.RETRYING}:
            continue
        satisfied = {TaskStatus.COMPLETED}
        if node.key in tolerant:
            satisfied |= {TaskStatus.FAILED, TaskStatus.SKIPPED}
            # A tolerant aggregator tolerates *some* dead branches, not all of
            # them: with nothing to aggregate it has no work to do, and
            # blocked_tasks() will skip it. Staying consistent with that here
            # keeps the two functions from contradicting each other.
            if node.dependencies and all(statuses.get(dep) in dead for dep in node.dependencies):
                continue
        if all(statuses.get(dep) in satisfied for dep in node.dependencies):
            ready.append(node.key)
    return ready


def blocked_tasks(
    nodes: Iterable[DagNode],
    statuses: Mapping[str, TaskStatus],
    *,
    tolerant_keys: Iterable[str] = (),
) -> list[str]:
    """Pending tasks that can never run because an ancestor failed or was cancelled."""
    dead = {
        key
        for key, status in statuses.items()
        if status in {TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.SKIPPED}
    }
    if not dead:
        return []

    tolerant = set(tolerant_keys)
    node_map = {node.key: node for node in nodes}
    blocked: list[str] = []
    for key, node in node_map.items():
        status = statuses.get(key)
        if status is None or status.is_terminal or status is TaskStatus.RUNNING:
            continue
        if key in tolerant:
            # A tolerant aggregator is only blocked when *every* branch died.
            branches = list(node.dependencies)
            if branches and all(dep in dead for dep in branches):
                blocked.append(key)
            continue
        if _has_dead_ancestor(node, node_map, dead, set(), tolerant):
            blocked.append(key)
    return blocked


def _has_dead_ancestor(
    node: DagNode,
    nodes: Mapping[str, DagNode],
    dead: set[str],
    seen: set[str],
    tolerant: set[str],
) -> bool:
    for dependency in node.dependencies:
        if dependency in seen:
            continue
        seen.add(dependency)
        if dependency in dead:
            return True
        if dependency in tolerant:
            # A *surviving* tolerant aggregator absorbs its dead branches, so we
            # stop looking past it. A dead one was caught by the check above.
            continue
        parent = nodes.get(dependency)
        if parent is not None and _has_dead_ancestor(parent, nodes, dead, seen, tolerant):
            return True
    return False


def plan_to_nodes(tasks: Sequence[TaskDefinition]) -> list[DagNode]:
    return [DagNode(key=task.id, dependencies=tuple(task.dependencies)) for task in tasks]
