"""Structured JSON logging with run/task correlation.

Correlation fields (``run_id``, ``task_id``, ``customer_id``, ``agent``,
``tool``, ``trace_id``) live in a :mod:`contextvars` context so any log record
emitted while a task executes carries them without threading arguments through
every function. Secret-looking values are redacted before they can reach a log
sink.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

from app.core.config import get_settings

# An immutable default: a shared mutable dict would leak fields between tasks.
_EMPTY: Mapping[str, Any] = MappingProxyType({})
_CONTEXT: ContextVar[Mapping[str, Any]] = ContextVar("veriflow_log_context", default=_EMPTY)

# Substring matches: any key containing one of these is redacted.
_SECRET_SUBSTRINGS = (
    "api_key",
    "apikey",
    "secret",
    "password",
    "passwd",
    "authorization",
    "credential",
    "private_key",
    "bearer",
)
# Suffix matches for the "*_token" family. Deliberately NOT a bare "token"
# substring: that would redact `prompt_tokens` and `total_tokens`, destroying the
# cost and usage telemetry this system is supposed to expose.
_SECRET_SUFFIXES = ("_token", "token_value")
_SECRET_EXACT = frozenset({"token", "key", "auth"})
_REDACTED = "***redacted***"

_STANDARD_ATTRS = frozenset(
    (
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    )
)


def redact(value: Any) -> Any:
    """Recursively mask values whose key looks like a credential."""
    if isinstance(value, dict):
        return {key: (_REDACTED if _is_secret_key(str(key)) else redact(inner)) for key, inner in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    if lowered in _SECRET_EXACT:
        return True
    if any(hint in lowered for hint in _SECRET_SUBSTRINGS):
        return True
    return any(lowered.endswith(suffix) for suffix in _SECRET_SUFFIXES)


def bind_context(**fields: Any) -> Token:
    """Add correlation fields to the logging context, returning a reset token."""
    merged = {**_CONTEXT.get(), **{k: v for k, v in fields.items() if v is not None}}
    return _CONTEXT.set(MappingProxyType(merged))


def reset_context(token: Token) -> None:
    _CONTEXT.reset(token)


def current_context() -> dict[str, Any]:
    return dict(_CONTEXT.get())


@contextmanager
def log_context(**fields: Any) -> Iterator[None]:
    token = bind_context(**fields)
    try:
        yield
    finally:
        reset_context(token)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(redact(current_context()))

        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _STANDARD_ATTRS and not key.startswith("_")
        }
        if extras:
            payload.update(redact(extras))

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = record.stack_info

        try:
            return json.dumps(payload, default=str)
        except (TypeError, ValueError):  # pragma: no cover - defensive
            return json.dumps({"level": record.levelname, "message": record.getMessage()})


_configured = False


def configure_logging(force: bool = False) -> None:
    global _configured
    if _configured and not force:
        return

    settings = get_settings()
    # stderr, not stdout: the CLIs in this package print machine-readable JSON
    # on stdout (`python -m app.seed.cli | jq`), and interleaved log lines would
    # make that unparseable. Docker collects both streams either way.
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level)

    # Uvicorn/Celery install their own handlers; route them through ours.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "celery", "celery.app.trace"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True

    logging.getLogger("sqlalchemy.engine").setLevel("WARNING")
    logging.getLogger("httpx").setLevel("WARNING")
    _configured = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)
