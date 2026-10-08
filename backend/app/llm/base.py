"""Provider-independent LLM interface.

Agents depend on this module only, never on a vendor SDK. Swapping providers (or
dropping in the deterministic fake used by the whole test suite) is a config
change, not a code change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class LLMMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class LLMRequest:
    """A single structured-output request.

    ``operation`` is a stable short name (``plan``, ``investigate``, ``verify``,
    ``report``) used for telemetry and for the fake provider's dispatch.
    """

    operation: str
    messages: list[LLMMessage]
    schema_name: str
    json_schema: dict[str, Any]
    temperature: float = 0.1
    max_output_tokens: int = 4096
    # Opaque payload forwarded to the fake provider so it can produce output
    # derived from real inputs rather than fixed strings.
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def prompt_text(self) -> str:
        return "\n\n".join(message.content for message in self.messages)


@dataclass(frozen=True)
class LLMUsage:
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    attempts: int = 1

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def merged(self, other: LLMUsage) -> LLMUsage:
        return LLMUsage(
            provider=self.provider,
            model=self.model,
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            latency_ms=self.latency_ms + other.latency_ms,
            attempts=self.attempts + other.attempts,
        )


@dataclass(frozen=True)
class LLMResponse:
    payload: dict[str, Any]
    usage: LLMUsage
    raw_text: str = ""


@dataclass(frozen=True)
class EmbeddingResponse:
    vectors: list[list[float]]
    usage: LLMUsage


@runtime_checkable
class LLMProvider(Protocol):
    name: str
    model: str

    def generate_json(self, request: LLMRequest) -> LLMResponse:
        """Return a JSON object conforming (best effort) to ``request.json_schema``."""

    def embed(self, texts: list[str]) -> EmbeddingResponse:
        """Return one embedding vector per input text."""


def estimate_tokens(text: str) -> int:
    """Cheap token estimate (~4 characters per token).

    Used by the fake provider and as a fallback when a provider omits usage, so
    cost/token dashboards stay populated instead of showing zeros.
    """
    return max(1, len(text) // 4)
