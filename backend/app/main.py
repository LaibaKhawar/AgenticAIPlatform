"""FastAPI application."""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1 import api_router
from app.api.v1.health import router as health_router
from app.core.config import get_settings
from app.core.errors import VeriflowError
from app.core.logging import configure_logging, get_logger, log_context
from app.core.telemetry import setup_telemetry
from app.db.session import database_healthy, dispose_engine

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging()
    setup_telemetry(service_name=settings.otel_service_name)
    ok, detail = database_healthy()
    logger.info(
        "api starting",
        extra={
            "environment": settings.app_env,
            "database_ok": ok,
            "database_detail": None if ok else detail,
            "llm_provider": settings.effective_llm_provider,
            "embedding_provider": settings.effective_embedding_provider,
            "executor": settings.workflow_executor,
            "failure_injection": settings.failure_injection_active,
            "auth": "api-key" if settings.api_key else "open (development)",
        },
    )
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        if settings.otel_enabled:
            FastAPIInstrumentor.instrument_app(app)
    except Exception as error:  # pragma: no cover - optional instrumentation
        logger.debug("fastapi instrumentation unavailable", extra={"error": str(error)})

    yield
    dispose_engine()
    logger.info("api stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=f"{settings.product_name} API",
        description=(
            f"{settings.product_name} — {settings.product_tagline}. "
            "Enterprise AI investigation and agent-orchestration platform."
        ),
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """Per-request id, size limit and structured access log."""
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > settings.api_max_request_bytes:
            return JSONResponse(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                content={
                    "error": {
                        "code": "payload_too_large",
                        "message": (f"Request body exceeds the {settings.api_max_request_bytes} byte limit."),
                    }
                },
            )

        started = time.perf_counter()
        with log_context(request_id=request_id):
            try:
                response = await call_next(request)
            except Exception:
                logger.exception(
                    "unhandled request error",
                    extra={"method": request.method, "path": request.url.path},
                )
                raise
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            response.headers["X-Request-ID"] = request_id
            if request.url.path not in {"/health/live", "/health/ready"}:
                logger.info(
                    "request completed",
                    extra={
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": response.status_code,
                        "duration_ms": duration_ms,
                    },
                )
            return response

    @app.exception_handler(VeriflowError)
    async def veriflow_error_handler(_request: Request, error: VeriflowError) -> JSONResponse:
        logger.warning("application error", extra={"code": error.code, "message": error.message})
        return JSONResponse(status_code=error.http_status, content=error.to_payload())

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, error: RequestValidationError) -> JSONResponse:
        """Validation errors that say what to fix, not just 'unprocessable'."""
        problems = [
            {
                "field": ".".join(str(part) for part in item["loc"][1:]) or str(item["loc"]),
                "message": item["msg"],
                "type": item["type"],
            }
            for item in error.errors()[:20]
        ]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "The request body or query parameters are invalid.",
                    "details": {"problems": problems},
                }
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(_request: Request, error: StarletteHTTPException) -> JSONResponse:
        detail = error.detail
        if isinstance(detail, dict) and "error" in detail:
            content = detail
        else:
            content = {"error": {"code": f"http_{error.status_code}", "message": str(detail)}}
        return JSONResponse(status_code=error.status_code, content=content, headers=error.headers)

    @app.exception_handler(Exception)
    async def unhandled_error_handler(_request: Request, error: Exception) -> JSONResponse:
        logger.exception("unhandled error", extra={"error_type": type(error).__name__})
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "An unexpected error occurred. The incident has been logged.",
                }
            },
        )

    app.include_router(health_router)
    app.include_router(api_router)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "product": settings.product_name,
            "tagline": settings.product_tagline,
            "docs": "/docs",
            "health": "/health",
            "api": "/api/v1",
        }

    return app


app = create_app()
