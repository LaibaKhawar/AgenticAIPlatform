"""Tool registry.

A tool is a *declared capability*: a name, a description, a validated Pydantic
input model, a typed output model, an access class, a timeout and a retry
policy. Agents may only call tools that appear in their own allow-list, which is
enforced here rather than in a prompt.

Deliberate non-features:

* there is no SQL tool — agents cannot author queries;
* there is no shell/filesystem/HTTP tool;
* every ``SENSITIVE_WRITE`` tool call is gated by the deterministic approval
  policy, and V1 ships none that execute externally (recommended actions become
  approval records instead).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.config import get_settings
from app.core.errors import (
    ToolInputError,
    ToolNotFoundError,
    ToolPermissionError,
    VeriflowError,
)
from app.core.logging import get_logger
from app.core.telemetry import span
from app.models.enums import ToolAccess

logger = get_logger(__name__)

TIn = TypeVar("TIn", bound=BaseModel)
TOut = TypeVar("TOut", bound=BaseModel)


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    retry_transient_only: bool = True


@dataclass
class ToolSpec(Generic[TIn, TOut]):
    name: str
    description: str
    input_model: type[TIn]
    output_model: type[TOut]
    handler: Callable[[Any, TIn], TOut]
    access: ToolAccess = ToolAccess.READ_ONLY
    timeout_seconds: float = 15.0
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    requires_approval: bool = False

    @property
    def is_write(self) -> bool:
        return self.access is ToolAccess.SENSITIVE_WRITE

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "access": self.access.value,
            "read_only": not self.is_write,
            "requires_approval": self.requires_approval,
            "timeout_seconds": self.timeout_seconds,
            "max_attempts": self.retry_policy.max_attempts,
            "input_schema": self.input_model.model_json_schema(),
            "output_schema": self.output_model.model_json_schema(),
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec[Any, Any]] = {}

    def register(self, spec: ToolSpec[Any, Any]) -> ToolSpec[Any, Any]:
        if spec.name in self._tools:
            raise ValueError(f"tool '{spec.name}' is already registered")
        self._tools[spec.name] = spec
        return spec

    def get(self, name: str) -> ToolSpec[Any, Any]:
        try:
            return self._tools[name]
        except KeyError as error:
            raise ToolNotFoundError(f"unknown tool: {name}") from error

    def names(self) -> list[str]:
        return sorted(self._tools)

    def describe_all(self) -> list[dict[str, Any]]:
        return [self._tools[name].describe() for name in self.names()]

    def __contains__(self, name: object) -> bool:
        return name in self._tools


REGISTRY = ToolRegistry()


def tool(
    *,
    name: str,
    description: str,
    input_model: type[TIn],
    output_model: type[TOut],
    access: ToolAccess = ToolAccess.READ_ONLY,
    timeout_seconds: float = 15.0,
    max_attempts: int = 3,
    requires_approval: bool = False,
) -> Callable[[Callable[[Any, TIn], TOut]], Callable[[Any, TIn], TOut]]:
    """Decorator registering a handler as a tool."""

    def decorator(handler: Callable[[Any, TIn], TOut]) -> Callable[[Any, TIn], TOut]:
        REGISTRY.register(
            ToolSpec(
                name=name,
                description=description,
                input_model=input_model,
                output_model=output_model,
                handler=handler,
                access=access,
                timeout_seconds=timeout_seconds,
                retry_policy=RetryPolicy(max_attempts=max_attempts),
                requires_approval=requires_approval,
            )
        )
        return handler

    return decorator


@dataclass
class ToolCallRecord:
    tool: str
    latency_ms: int
    ok: bool
    error: str | None = None


class ToolContext:
    """Execution context handed to a tool handler.

    Carries the database session and run/customer correlation. A tool never
    receives the raw request or any credential.
    """

    def __init__(self, session: Any, *, run_id: Any = None, task_key: str | None = None) -> None:
        self.session = session
        self.run_id = run_id
        self.task_key = task_key


class ToolInvoker:
    """Calls tools on behalf of one agent, enforcing permissions and budgets."""

    def __init__(
        self,
        *,
        agent_name: str,
        allowed_tools: set[str],
        context: ToolContext,
        registry: ToolRegistry | None = None,
        max_calls: int | None = None,
    ) -> None:
        self.agent_name = agent_name
        self.allowed_tools = allowed_tools
        self.context = context
        self.registry = registry or REGISTRY
        self.max_calls = max_calls or get_settings().max_tool_calls_per_task
        self.calls: list[ToolCallRecord] = []

    def call(self, name: str, payload: dict[str, Any] | BaseModel) -> BaseModel:
        spec = self.registry.get(name)
        if name not in self.allowed_tools:
            raise ToolPermissionError(
                f"agent '{self.agent_name}' is not permitted to call tool '{name}'",
                details={"agent": self.agent_name, "tool": name, "allowed": sorted(self.allowed_tools)},
            )
        if len(self.calls) >= self.max_calls:
            raise ToolPermissionError(
                f"agent '{self.agent_name}' exceeded its tool-call budget of {self.max_calls}",
                details={"agent": self.agent_name, "tool": name},
            )

        try:
            validated = payload if isinstance(payload, spec.input_model) else spec.input_model.model_validate(payload)
        except ValidationError as error:
            raise ToolInputError(f"invalid input for tool '{name}'", details={"errors": error.errors()[:10]}) from error

        started = time.perf_counter()
        with span(
            "tool_call",
            **{"tool.name": name, "tool.agent": self.agent_name, "tool.access": spec.access.value},
        ):
            try:
                result = spec.handler(self.context, validated)
            except VeriflowError as error:
                latency = int((time.perf_counter() - started) * 1000)
                self.calls.append(ToolCallRecord(tool=name, latency_ms=latency, ok=False, error=str(error)))
                logger.warning(
                    "tool call failed",
                    extra={"tool": name, "agent": self.agent_name, "latency_ms": latency, "error": str(error)},
                )
                raise

        latency = int((time.perf_counter() - started) * 1000)
        self.calls.append(ToolCallRecord(tool=name, latency_ms=latency, ok=True))
        logger.info(
            "tool call completed",
            extra={"tool": name, "agent": self.agent_name, "latency_ms": latency},
        )
        return result

    def usage(self) -> dict[str, Any]:
        return {
            "total_calls": len(self.calls),
            "failed_calls": sum(1 for call in self.calls if not call.ok),
            "total_latency_ms": sum(call.latency_ms for call in self.calls),
            "by_tool": {
                name: sum(1 for call in self.calls if call.tool == name) for name in {call.tool for call in self.calls}
            },
        }
