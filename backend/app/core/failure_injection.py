"""Development-only fault simulation.

Used to prove that the retry/recovery paths actually work rather than asserting
that they exist. Hard-disabled when ``APP_ENV=production`` (see
``Settings.failure_injection_active``), and deterministic when a seed is given
so tests can assert specific recovery behaviour.
"""

from __future__ import annotations

import random
from typing import Literal

from app.core.config import get_settings
from app.core.errors import (
    ExternalServiceError,
    LLMRateLimitError,
    LLMTimeoutError,
    StructuredOutputError,
    VectorSearchError,
    VeriflowError,
)
from app.core.logging import get_logger

logger = get_logger(__name__)

Surface = Literal["llm", "vector", "api"]

_LLM_FAULTS = (
    ("rate_limit", LLMRateLimitError("Injected fault: LLM rate limited (429)")),
    ("timeout", LLMTimeoutError("Injected fault: LLM request timed out")),
    ("malformed", StructuredOutputError("Injected fault: model returned malformed JSON")),
)


class FailureInjector:
    """Rolls a die before an operation and raises a realistic failure."""

    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng or random.Random()

    def _rate(self, surface: Surface) -> float:
        settings = get_settings()
        if not settings.failure_injection_active:
            return 0.0
        return {
            "llm": settings.llm_failure_rate,
            "vector": settings.vector_failure_rate,
            "api": settings.api_failure_rate,
        }[surface]

    def maybe_fail(self, surface: Surface, *, operation: str = "") -> None:
        rate = self._rate(surface)
        if rate <= 0.0 or self._rng.random() >= rate:
            return

        kind: str
        error: VeriflowError
        if surface == "llm":
            kind, error = _LLM_FAULTS[self._rng.randrange(len(_LLM_FAULTS))]
        elif surface == "vector":
            kind, error = "vector_unavailable", VectorSearchError("Injected fault: vector search unavailable")
        else:
            kind, error = "service_unavailable", ExternalServiceError("Injected fault: downstream service unavailable")

        logger.warning(
            "failure injection triggered",
            extra={"surface": surface, "fault": kind, "operation": operation, "rate": rate},
        )
        raise error


_injector = FailureInjector()


def get_injector() -> FailureInjector:
    return _injector


def set_injector(injector: FailureInjector) -> None:
    """Install a seeded injector (tests, reproducible demos)."""
    global _injector
    _injector = injector
