"""Error taxonomy.

The retry policy is driven by *type*, not by string matching: everything that
derives from :class:`TransientError` is retried with backoff, everything that
derives from :class:`PermanentError` fails the task immediately. New failure
modes must pick a side explicitly.
"""

from __future__ import annotations

from typing import Any


class VeriflowError(Exception):
    """Base class for all application errors."""

    code = "veriflow_error"
    http_status = 500

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_payload(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


# --- Transient (retryable) ---------------------------------------------------


class TransientError(VeriflowError):
    code = "transient_error"
    http_status = 503


class LLMRateLimitError(TransientError):
    code = "llm_rate_limited"


class LLMServiceError(TransientError):
    code = "llm_service_error"


class LLMTimeoutError(TransientError):
    code = "llm_timeout"


class EmbeddingServiceError(TransientError):
    code = "embedding_service_error"


class VectorSearchError(TransientError):
    code = "vector_search_error"


class DatabaseTransientError(TransientError):
    code = "database_transient_error"


class ExternalServiceError(TransientError):
    code = "external_service_error"


# --- Permanent (non-retryable) ----------------------------------------------


class PermanentError(VeriflowError):
    code = "permanent_error"
    http_status = 400


class StructuredOutputError(PermanentError):
    """The model could not produce schema-valid output within the retry budget."""

    code = "invalid_structured_output"


class PlanValidationError(PermanentError):
    code = "invalid_plan"


class ToolNotFoundError(PermanentError):
    code = "tool_not_found"
    http_status = 404


class ToolPermissionError(PermanentError):
    code = "tool_permission_denied"
    http_status = 403


class ToolInputError(PermanentError):
    code = "tool_input_invalid"
    http_status = 422


class UnsupportedObjectiveError(PermanentError):
    code = "unsupported_objective"
    http_status = 422


class ResourceNotFoundError(PermanentError):
    code = "not_found"
    http_status = 404


class ConflictError(PermanentError):
    code = "conflict"
    http_status = 409


class WorkflowCancelledError(PermanentError):
    """Raised to unwind a task whose run was cancelled underneath it."""

    code = "run_cancelled"
    http_status = 409


class ApprovalRequiredError(VeriflowError):
    """Control-flow signal: the task cannot continue until a human decides."""

    code = "approval_required"
    http_status = 202


def is_retryable(error: BaseException) -> bool:
    """Classify an exception for the retry policy.

    Unknown exceptions are treated as permanent: a bug should surface as a clear
    failed run instead of being retried three times and hidden.
    """
    if isinstance(error, TransientError):
        return True
    if isinstance(error, (PermanentError, ApprovalRequiredError)):
        return False
    return isinstance(error, (TimeoutError, ConnectionError))
