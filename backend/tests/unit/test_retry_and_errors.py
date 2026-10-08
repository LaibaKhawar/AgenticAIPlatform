"""Retry classification, backoff and failure-injection behaviour."""

from __future__ import annotations

import random

import pytest

from app.core import failure_injection as fi
from app.core.config import get_settings
from app.core.errors import (
    ApprovalRequiredError,
    ConflictError,
    DatabaseTransientError,
    EmbeddingServiceError,
    LLMRateLimitError,
    LLMServiceError,
    LLMTimeoutError,
    PlanValidationError,
    ResourceNotFoundError,
    StructuredOutputError,
    ToolPermissionError,
    UnsupportedObjectiveError,
    VectorSearchError,
    VeriflowError,
    WorkflowCancelledError,
    is_retryable,
)
from app.core.retry import backoff_delay, retry_call

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "error",
    [
        LLMRateLimitError("429"),
        LLMServiceError("502"),
        LLMTimeoutError("timeout"),
        EmbeddingServiceError("embedding down"),
        VectorSearchError("vector timeout"),
        DatabaseTransientError("connection reset"),
        TimeoutError("socket timeout"),
        ConnectionError("refused"),
    ],
)
def test_transient_errors_are_retryable(error: BaseException) -> None:
    assert is_retryable(error) is True


@pytest.mark.parametrize(
    "error",
    [
        StructuredOutputError("bad schema"),
        PlanValidationError("cyclic plan"),
        ResourceNotFoundError("no such customer"),
        ToolPermissionError("not allowed"),
        UnsupportedObjectiveError("out of scope"),
        ConflictError("already resolved"),
        WorkflowCancelledError("cancelled"),
        ApprovalRequiredError("needs a human"),
    ],
)
def test_permanent_errors_are_not_retryable(error: BaseException) -> None:
    assert is_retryable(error) is False


def test_unknown_exceptions_are_treated_as_permanent() -> None:
    """A bug must surface as a clear failure, not be retried three times."""
    assert is_retryable(ValueError("a bug")) is False
    assert is_retryable(KeyError("missing")) is False
    assert is_retryable(ZeroDivisionError()) is False


def test_error_payload_shape_is_stable() -> None:
    error = ToolPermissionError("nope", details={"tool": "x"})
    payload = error.to_payload()
    assert payload["error"]["code"] == "tool_permission_denied"
    assert payload["error"]["message"] == "nope"
    assert payload["error"]["details"] == {"tool": "x"}
    assert error.http_status == 403


def test_every_error_subclass_declares_a_code() -> None:
    def subclasses(cls: type) -> list[type]:
        found = []
        for child in cls.__subclasses__():
            found.append(child)
            found.extend(subclasses(child))
        return found

    for cls in subclasses(VeriflowError):
        assert cls.code, f"{cls.__name__} has no error code"


# --------------------------------------------------------------------------- #
# Backoff
# --------------------------------------------------------------------------- #


def test_backoff_grows_exponentially_without_jitter() -> None:
    delays = [backoff_delay(attempt, base=1.0, cap=60.0, jitter=False) for attempt in (1, 2, 3, 4)]
    assert delays == [1.0, 2.0, 4.0, 8.0]


def test_backoff_is_capped() -> None:
    assert backoff_delay(20, base=1.0, cap=30.0, jitter=False) == 30.0


def test_backoff_jitter_stays_within_the_ceiling() -> None:
    rng = random.Random(7)
    for attempt in (1, 2, 3, 4, 5):
        ceiling = min(30.0, 1.0 * 2 ** (attempt - 1))
        for _ in range(20):
            delay = backoff_delay(attempt, base=1.0, cap=30.0, rng=rng)
            assert 0.0 <= delay <= ceiling


def test_backoff_jitter_actually_varies() -> None:
    rng = random.Random(11)
    values = {backoff_delay(4, base=1.0, cap=30.0, rng=rng) for _ in range(25)}
    assert len(values) > 10, "full jitter must spread retries, not return one value"


def test_backoff_treats_attempt_zero_as_the_first_attempt() -> None:
    assert backoff_delay(0, base=2.0, cap=60.0, jitter=False) == 2.0


# --------------------------------------------------------------------------- #
# retry_call
# --------------------------------------------------------------------------- #


def test_retry_call_recovers_after_transient_failures() -> None:
    attempts = {"n": 0}

    def flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise LLMRateLimitError("429")
        return "ok"

    assert retry_call(flaky, max_attempts=4, sleep=lambda _s: None) == "ok"
    assert attempts["n"] == 3


def test_retry_call_exhausts_its_budget_and_reraises() -> None:
    attempts = {"n": 0}

    def always_failing() -> None:
        attempts["n"] += 1
        raise LLMServiceError("503")

    with pytest.raises(LLMServiceError):
        retry_call(always_failing, max_attempts=3, sleep=lambda _s: None)
    assert attempts["n"] == 3, "the budget must be used exactly once per attempt"


def test_retry_call_does_not_retry_permanent_errors() -> None:
    attempts = {"n": 0}

    def permanent() -> None:
        attempts["n"] += 1
        raise StructuredOutputError("invalid json")

    with pytest.raises(StructuredOutputError):
        retry_call(permanent, max_attempts=5, sleep=lambda _s: None)
    assert attempts["n"] == 1


def test_retry_call_sleeps_between_attempts() -> None:
    slept: list[float] = []

    def flaky() -> str:
        if len(slept) < 2:
            raise LLMTimeoutError("timeout")
        return "done"

    assert retry_call(flaky, max_attempts=5, sleep=slept.append) == "done"
    assert len(slept) == 2
    assert all(delay >= 0 for delay in slept)


def test_retry_call_returns_immediately_on_success() -> None:
    calls = {"n": 0}

    def ok() -> int:
        calls["n"] += 1
        return 42

    assert retry_call(ok, max_attempts=3, sleep=lambda _s: None) == 42
    assert calls["n"] == 1


# --------------------------------------------------------------------------- #
# Failure injection
# --------------------------------------------------------------------------- #


def test_injection_is_inert_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "failure_injection_enabled", False)
    injector = fi.FailureInjector(random.Random(1))
    for _ in range(50):
        injector.maybe_fail("llm")  # must never raise


def test_injection_raises_transient_llm_faults_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "failure_injection_enabled", True)
    monkeypatch.setattr(settings, "app_env", "local")
    monkeypatch.setattr(settings, "llm_failure_rate", 1.0)

    injector = fi.FailureInjector(random.Random(3))
    raised: list[type[BaseException]] = []
    for _ in range(30):
        try:
            injector.maybe_fail("llm")
        except BaseException as error:
            raised.append(type(error))

    assert len(raised) == 30
    assert {LLMRateLimitError, LLMTimeoutError, StructuredOutputError} == set(raised)


def test_vector_injection_raises_a_retryable_vector_error(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "failure_injection_enabled", True)
    monkeypatch.setattr(settings, "app_env", "local")
    monkeypatch.setattr(settings, "vector_failure_rate", 1.0)
    with pytest.raises(VectorSearchError) as error:
        fi.FailureInjector(random.Random(5)).maybe_fail("vector")
    assert is_retryable(error.value)


def test_injection_is_hard_disabled_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    """Production safety is not a matter of remembering to set the rate to 0."""
    settings = get_settings()
    monkeypatch.setattr(settings, "failure_injection_enabled", True)
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "llm_failure_rate", 1.0)

    assert settings.failure_injection_active is False
    injector = fi.FailureInjector(random.Random(9))
    for _ in range(25):
        injector.maybe_fail("llm")


def test_injection_rate_is_respected(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "failure_injection_enabled", True)
    monkeypatch.setattr(settings, "app_env", "local")
    monkeypatch.setattr(settings, "llm_failure_rate", 0.5)

    injector = fi.FailureInjector(random.Random(2024))
    failures = 0
    for _ in range(400):
        try:
            injector.maybe_fail("llm")
        except BaseException:
            failures += 1
    assert 150 <= failures <= 250, f"expected roughly half of 400, got {failures}"
