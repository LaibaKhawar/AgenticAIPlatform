"""The single entry point agents use to call a model.

Responsibilities, in order:

1. inject development faults (so recovery paths are exercised),
2. retry transient provider failures with exponential backoff + jitter,
3. validate the response against a Pydantic model,
4. on validation failure, re-prompt once per remaining attempt with the
   validation error appended — then fail the task with
   :class:`StructuredOutputError` rather than accepting malformed output,
5. record latency, tokens, estimated cost and validity for every call.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.config import get_settings
from app.core.errors import StructuredOutputError
from app.core.failure_injection import get_injector
from app.core.logging import get_logger
from app.core.retry import retry_call
from app.core.telemetry import get_langfuse, span
from app.llm.base import LLMMessage, LLMProvider, LLMRequest, LLMResponse, LLMUsage
from app.llm.fake_provider import FakeLLMProvider

logger = get_logger(__name__)

TModel = TypeVar("TModel", bound=BaseModel)


def build_provider() -> LLMProvider:
    settings = get_settings()
    if settings.effective_llm_provider == "openai":
        from app.llm.openai_provider import OpenAIProvider

        return OpenAIProvider()
    if settings.llm_provider == "openai" and not settings.openai_api_key:
        logger.warning(
            "falling back to the deterministic provider",
            extra={"reason": "LLM_PROVIDER=openai but OPENAI_API_KEY is unset"},
        )
    return FakeLLMProvider()


@dataclass
class CallRecord:
    """What a caller needs to persist about an LLM call."""

    agent: str
    operation: str
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    estimated_cost_usd: float
    attempts: int
    valid_output: bool


def estimate_cost(usage: LLMUsage) -> float:
    settings = get_settings()
    return round(
        usage.prompt_tokens / 1_000_000 * settings.llm_input_cost_per_mtok
        + usage.completion_tokens / 1_000_000 * settings.llm_output_cost_per_mtok,
        6,
    )


class LLMClient:
    """Provider-agnostic structured-output client."""

    def __init__(self, provider: LLMProvider | None = None) -> None:
        self._provider = provider or build_provider()
        self.records: list[CallRecord] = []

    @property
    def provider_name(self) -> str:
        return self._provider.name

    @property
    def model(self) -> str:
        return self._provider.model

    def structured(
        self,
        *,
        operation: str,
        agent: str,
        system_prompt: str,
        user_prompt: str,
        output_model: type[TModel],
        context: dict[str, Any] | None = None,
        run_id: uuid.UUID | str | None = None,
        temperature: float | None = None,
    ) -> tuple[TModel, CallRecord]:
        settings = get_settings()
        schema = output_model.model_json_schema()
        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=user_prompt),
        ]
        request = LLMRequest(
            operation=operation,
            messages=messages,
            schema_name=output_model.__name__,
            json_schema=schema,
            temperature=settings.llm_temperature if temperature is None else temperature,
            max_output_tokens=settings.llm_max_output_tokens,
            context=context or {},
        )

        total_usage = LLMUsage(provider=self._provider.name, model=self._provider.model, attempts=0)
        attempts = 0
        last_error: str | None = None
        max_attempts = settings.llm_structured_output_retries + 1

        with span(
            "llm_call",
            **{"llm.operation": operation, "llm.agent": agent, "llm.model": self._provider.model},
        ) as current_span:
            for attempt in range(1, max_attempts + 1):
                attempts = attempt
                if last_error is not None:
                    # Feed the validation error back so the model can repair it.
                    request.messages = [
                        *messages,
                        LLMMessage(
                            role="user",
                            content=(
                                "Your previous response did not satisfy the required schema.\n"
                                f"Validation error:\n{last_error}\n\n"
                                "Return corrected JSON that satisfies the schema exactly. "
                                "Do not add commentary."
                            ),
                        ),
                    ]

                response = self._call_provider(request, operation=operation)
                total_usage = total_usage.merged(response.usage)
                try:
                    parsed = output_model.model_validate(response.payload)
                except ValidationError as error:
                    last_error = _format_validation_error(error)
                    logger.warning(
                        "structured output failed validation",
                        extra={
                            "agent": agent,
                            "operation": operation,
                            "attempt": attempt,
                            "schema": output_model.__name__,
                            "validation_error": last_error[:1000],
                        },
                    )
                    current_span.set_attribute("llm.validation_failures", attempt)
                    continue

                record = self._record(
                    agent=agent,
                    operation=operation,
                    usage=total_usage,
                    attempts=attempts,
                    valid_output=True,
                )
                get_langfuse().log_generation(
                    name=f"{agent}.{operation}",
                    model=self._provider.model,
                    run_id=str(run_id) if run_id else None,
                    input_payload={"system": system_prompt, "user": user_prompt},
                    output_payload=response.payload,
                    usage={
                        "promptTokens": total_usage.prompt_tokens,
                        "completionTokens": total_usage.completion_tokens,
                    },
                    metadata={"agent": agent, "operation": operation, "attempts": attempts},
                )
                return parsed, record

        self._record(agent=agent, operation=operation, usage=total_usage, attempts=attempts, valid_output=False)
        raise StructuredOutputError(
            f"{agent} could not produce valid {output_model.__name__} output after {attempts} attempt(s)",
            details={"schema": output_model.__name__, "last_validation_error": last_error},
        )

    # --- internals --------------------------------------------------------

    def _call_provider(self, request: LLMRequest, *, operation: str) -> LLMResponse:
        def invoke() -> LLMResponse:
            get_injector().maybe_fail("llm", operation=operation)
            return self._provider.generate_json(request)

        return retry_call(
            invoke,
            max_attempts=get_settings().task_max_retries,
            operation=f"llm:{operation}",
        )

    def _record(self, *, agent: str, operation: str, usage: LLMUsage, attempts: int, valid_output: bool) -> CallRecord:
        record = CallRecord(
            agent=agent,
            operation=operation,
            provider=self._provider.name,
            model=self._provider.model,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            latency_ms=usage.latency_ms,
            estimated_cost_usd=estimate_cost(usage),
            attempts=attempts,
            valid_output=valid_output,
        )
        self.records.append(record)
        logger.info(
            "llm call completed",
            extra={
                "agent": agent,
                "operation": operation,
                "provider": record.provider,
                "model": record.model,
                "prompt_tokens": record.prompt_tokens,
                "completion_tokens": record.completion_tokens,
                "latency_ms": record.latency_ms,
                "estimated_cost_usd": record.estimated_cost_usd,
                "attempts": attempts,
                "valid_output": valid_output,
            },
        )
        return record


def _format_validation_error(error: ValidationError) -> str:
    lines = []
    for item in error.errors()[:10]:
        location = ".".join(str(part) for part in item["loc"])
        lines.append(f"- {location or '<root>'}: {item['msg']}")
    return "\n".join(lines)


def json_preview(payload: Any, limit: int = 2000) -> str:
    try:
        text = json.dumps(payload, indent=2, default=str)
    except (TypeError, ValueError):
        text = str(payload)
    return text if len(text) <= limit else text[:limit] + "\n… (truncated)"
