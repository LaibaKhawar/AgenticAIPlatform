"""Base agent.

An agent is a declared, bounded capability: a name, a role, an explicit tool
allow-list, a model configuration, a prompt, a typed output schema, a timeout
and a retry budget. Everything an agent can do is visible in its declaration —
there is no dynamic capability acquisition and no agent-to-agent chatter.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel

from app.core.config import get_settings
from app.core.logging import get_logger, log_context
from app.core.telemetry import span
from app.llm.client import CallRecord, LLMClient
from app.models.enums import AgentType
from app.tools.registry import REGISTRY, ToolContext, ToolInvoker, ToolRegistry

logger = get_logger(__name__)

TModel = TypeVar("TModel", bound=BaseModel)


@dataclass
class AgentConfig:
    agent_type: AgentType
    role: str
    allowed_tools: tuple[str, ...] = ()
    temperature: float | None = None
    timeout_seconds: float = 120.0
    max_retries: int = 2
    uses_llm: bool = True

    def validate_against(self, registry: ToolRegistry) -> None:
        unknown = [name for name in self.allowed_tools if name not in registry]
        if unknown:
            raise ValueError(f"agent '{self.agent_type.value}' declares unknown tool(s): {unknown}")


@dataclass
class AgentRunContext:
    """Correlation and dependency injection for one agent invocation."""

    session: Any
    run_id: uuid.UUID | None = None
    task_key: str | None = None
    customer_id: uuid.UUID | None = None
    llm: LLMClient | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class BaseAgent:
    config: AgentConfig

    def __init__(self, *, llm: LLMClient | None = None, registry: ToolRegistry | None = None) -> None:
        self.registry = registry or REGISTRY
        self.config.validate_against(self.registry)
        self._llm = llm

    # --- identity ---------------------------------------------------------

    @property
    def name(self) -> str:
        return self.config.agent_type.value

    @property
    def role(self) -> str:
        return self.config.role

    @property
    def allowed_tools(self) -> set[str]:
        return set(self.config.allowed_tools)

    def describe(self) -> dict[str, Any]:
        settings = get_settings()
        return {
            "name": self.name,
            "role": self.role,
            "uses_llm": self.config.uses_llm,
            "model": settings.llm_model if self.config.uses_llm else None,
            "provider": settings.effective_llm_provider if self.config.uses_llm else None,
            "allowed_tools": sorted(self.allowed_tools),
            "timeout_seconds": self.config.timeout_seconds,
            "max_retries": self.config.max_retries,
            "output_schema": self.output_schema_name(),
        }

    def output_schema_name(self) -> str | None:
        return None

    # --- collaborators ----------------------------------------------------

    def llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient()
        return self._llm

    def invoker(self, context: AgentRunContext) -> ToolInvoker:
        return ToolInvoker(
            agent_name=self.name,
            allowed_tools=self.allowed_tools,
            context=ToolContext(context.session, run_id=context.run_id, task_key=context.task_key),
            registry=self.registry,
        )

    # --- model call -------------------------------------------------------

    def call_model(
        self,
        context: AgentRunContext,
        *,
        operation: str,
        system_prompt: str,
        user_prompt: str,
        output_model: type[TModel],
        payload: dict[str, Any] | None = None,
    ) -> tuple[TModel, CallRecord]:
        client = context.llm or self.llm()
        return client.structured(
            operation=operation,
            agent=self.name,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            output_model=output_model,
            context=payload or {},
            run_id=context.run_id,
            temperature=self.config.temperature,
        )

    # --- execution wrapper ------------------------------------------------

    def traced(self, context: AgentRunContext, span_name: str) -> Any:
        """Span + log-context manager used by concrete agents."""

        class _Scope:
            def __init__(self, agent: BaseAgent) -> None:
                self._agent = agent
                self._span: Any = None
                self._log: Any = None

            def __enter__(self) -> None:
                self._log = log_context(
                    agent=self._agent.name,
                    run_id=str(context.run_id) if context.run_id else None,
                    task=context.task_key,
                    customer_id=str(context.customer_id) if context.customer_id else None,
                )
                self._log.__enter__()
                self._span = span(span_name, **{"agent.name": self._agent.name})
                self._span.__enter__()

            def __exit__(self, *exc: Any) -> None:
                self._span.__exit__(*exc)
                self._log.__exit__(*exc)

        return _Scope(self)


SYSTEM_PREAMBLE = (
    "You are a component of {product}, an enterprise AI investigation platform used by customer "
    "success and revenue teams. You operate inside a deterministic workflow and your output is "
    "machine-consumed.\n\n"
    "Non-negotiable rules:\n"
    "1. Respond with JSON matching the provided schema. No prose outside the JSON.\n"
    "2. Never compute or restate a metric that was not supplied to you. All arithmetic, dates, "
    "rankings and scores are computed by the platform and given to you as inputs.\n"
    "3. Every factual statement you make must cite the reference id of the evidence that supports "
    "it. If you cannot cite evidence, do not make the statement.\n"
    "4. Distinguish what was observed, what was calculated, and what you infer. Never write an "
    "inference as settled fact.\n"
    "5. If the data is insufficient, say so explicitly. An honest 'insufficient evidence' is "
    "correct; an invented detail is a defect.\n"
)


def system_prompt(body: str) -> str:
    settings = get_settings()
    return SYSTEM_PREAMBLE.format(product=settings.product_name) + "\n" + body
