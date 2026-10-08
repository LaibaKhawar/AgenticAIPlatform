"""SQLAlchemy models. Importing this package registers every table on ``Base``."""

from app.db.base import Base
from app.models.domain import (
    Customer,
    CustomerDocument,
    CustomerOutcomeRecord,
    DocumentChunk,
    NpsSurvey,
    Payment,
    ProductUsage,
    Subscription,
    SupportTicket,
)
from app.models.workflow import (
    Approval,
    AuditEvent,
    Claim,
    EvaluationRun,
    Evidence,
    Investigation,
    LlmCall,
    Report,
    Run,
    RunTask,
    claim_evidence,
)

__all__ = [
    "Approval",
    "AuditEvent",
    "Base",
    "Claim",
    "Customer",
    "CustomerDocument",
    "CustomerOutcomeRecord",
    "DocumentChunk",
    "EvaluationRun",
    "Evidence",
    "Investigation",
    "LlmCall",
    "NpsSurvey",
    "Payment",
    "ProductUsage",
    "Report",
    "Run",
    "RunTask",
    "Subscription",
    "SupportTicket",
    "claim_evidence",
]
