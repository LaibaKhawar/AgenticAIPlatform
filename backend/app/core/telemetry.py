"""OpenTelemetry tracing plus optional Langfuse trace export.

Tracing is always available as an API: when OTEL is disabled the SDK's no-op
tracer is used, so instrumentation code never needs an ``if enabled`` guard.
Langfuse is used through its public ingestion HTTP API when credentials are
configured — it is strictly optional and failures never affect a workflow.
"""

from __future__ import annotations

import base64
import json
import threading
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import httpx
from opentelemetry import trace
from opentelemetry.trace import Span, SpanKind, Status, StatusCode

from app.core.config import get_settings
from app.core.logging import get_logger, log_context

logger = get_logger(__name__)
_initialised = False
_lock = threading.Lock()


def setup_telemetry(service_name: str | None = None) -> None:
    """Install the OTLP exporter once per process when enabled."""
    global _initialised
    settings = get_settings()
    with _lock:
        if _initialised:
            return
        _initialised = True
        if not settings.otel_enabled:
            logger.info("tracing disabled", extra={"reason": "OTEL_ENABLED=false"})
            return
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            resource = Resource.create(
                {
                    "service.name": service_name or settings.otel_service_name,
                    "service.version": "1.0.0",
                    "deployment.environment": settings.app_env,
                }
            )
            provider = TracerProvider(resource=resource)
            if settings.otel_exporter_otlp_endpoint:
                provider.add_span_processor(
                    BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{settings.otel_exporter_otlp_endpoint}/v1/traces"))
                )
            trace.set_tracer_provider(provider)
            logger.info(
                "tracing enabled",
                extra={"endpoint": settings.otel_exporter_otlp_endpoint, "service": service_name},
            )
        except Exception as error:  # pragma: no cover - exporter wiring
            logger.warning("tracing setup failed", extra={"error": str(error)})


def get_tracer(name: str = "veriflow") -> trace.Tracer:
    return trace.get_tracer(name)


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[Span]:
    """Start a span and bind its trace id into the structured-logging context."""
    tracer = get_tracer()
    with tracer.start_as_current_span(name, kind=SpanKind.INTERNAL) as current:
        for key, value in attributes.items():
            if value is not None:
                current.set_attribute(key, value if isinstance(value, (str, int, float, bool)) else str(value))
        context = current.get_span_context()
        trace_id = format(context.trace_id, "032x") if context.trace_id else None
        with log_context(trace_id=trace_id, span=name):
            try:
                yield current
            except Exception as error:
                current.set_status(Status(StatusCode.ERROR, str(error)))
                current.record_exception(error)
                raise


def current_trace_id() -> str | None:
    context = trace.get_current_span().get_span_context()
    if not context.trace_id:
        return None
    return format(context.trace_id, "032x")


class LangfuseClient:
    """Minimal Langfuse ingestion client (optional, best-effort, non-blocking path).

    We deliberately avoid the vendor SDK: a single documented HTTP endpoint keeps
    the dependency surface small and makes the "works without Langfuse" promise
    easy to honour.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self.enabled = settings.langfuse_configured
        self._host = settings.langfuse_host.rstrip("/")
        if self.enabled:
            token = base64.b64encode(f"{settings.langfuse_public_key}:{settings.langfuse_secret_key}".encode()).decode()
            self._headers = {"Authorization": f"Basic {token}", "Content-Type": "application/json"}

    def log_generation(
        self,
        *,
        name: str,
        model: str,
        run_id: str | None,
        input_payload: Any,
        output_payload: Any,
        usage: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        if not self.enabled:
            return
        now = datetime.now(tz=UTC).isoformat()
        body = {
            "batch": [
                {
                    "id": str(uuid.uuid4()),
                    "timestamp": now,
                    "type": "generation-create",
                    "body": {
                        "id": str(uuid.uuid4()),
                        "traceId": run_id or str(uuid.uuid4()),
                        "name": name,
                        "model": model,
                        "startTime": now,
                        "endTime": now,
                        "input": _truncate(input_payload),
                        "output": _truncate(output_payload),
                        "usage": dict(usage or {}),
                        "metadata": dict(metadata or {}),
                    },
                }
            ]
        }
        try:
            with httpx.Client(timeout=5.0) as client:
                client.post(f"{self._host}/api/public/ingestion", headers=self._headers, json=body)
        except Exception as error:  # pragma: no cover - network best effort
            logger.debug("langfuse export failed", extra={"error": str(error)})


def _truncate(payload: Any, limit: int = 8000) -> Any:
    try:
        text = json.dumps(payload, default=str)
    except (TypeError, ValueError):
        text = str(payload)
    return text[:limit]


_langfuse: LangfuseClient | None = None


def get_langfuse() -> LangfuseClient:
    global _langfuse
    if _langfuse is None:
        _langfuse = LangfuseClient()
    return _langfuse
