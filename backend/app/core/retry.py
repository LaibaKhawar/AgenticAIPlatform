"""Exponential backoff with full jitter."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import TypeVar

from app.core.config import get_settings
from app.core.errors import is_retryable
from app.core.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


def backoff_delay(
    attempt: int,
    *,
    base: float | None = None,
    cap: float | None = None,
    jitter: bool = True,
    rng: random.Random | None = None,
) -> float:
    """Delay before retry ``attempt`` (1 = after the first failure).

    ``min(cap, base * 2**(attempt-1))`` with full jitter, which spreads a
    thundering herd of workers that all got rate-limited at the same moment.
    """
    settings = get_settings()
    base = settings.retry_base_delay_seconds if base is None else base
    cap = settings.retry_max_delay_seconds if cap is None else cap
    attempt = max(1, attempt)
    ceiling = min(cap, base * (2 ** (attempt - 1)))
    if not jitter:
        return ceiling
    return (rng or random).uniform(0.0, ceiling)


def retry_call(
    func: Callable[[], T],
    *,
    max_attempts: int = 3,
    operation: str = "operation",
    sleep: Callable[[float], None] = time.sleep,
    rng: random.Random | None = None,
) -> T:
    """Call ``func`` retrying only transient failures.

    Returns the first successful result; re-raises the last error once the
    attempt budget is exhausted or the error is classified as permanent.
    """
    last_error: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return func()
        except BaseException as error:
            last_error = error
            if not is_retryable(error) or attempt == max_attempts:
                raise
            delay = backoff_delay(attempt, rng=rng)
            logger.warning(
                "retrying after transient failure",
                extra={
                    "operation": operation,
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "delay_seconds": round(delay, 3),
                    "error_type": type(error).__name__,
                    "error": str(error)[:500],
                },
            )
            sleep(delay)
    raise last_error  # type: ignore[misc]  # pragma: no cover - unreachable
