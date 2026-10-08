"""Domain and workflow enumerations.

These are stored as text with CHECK constraints rather than PostgreSQL ENUM
types: adding a value is a plain constraint change instead of a type migration,
and the values stay readable in `psql`.
"""

from __future__ import annotations

from enum import StrEnum


class AccountTier(StrEnum):
    ENTERPRISE = "ENTERPRISE"
    MID_MARKET = "MID_MARKET"
    SMB = "SMB"
    STARTUP = "STARTUP"


class SubscriptionStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    CANCELLED = "CANCELLED"
    PAUSED = "PAUSED"


class PaymentStatus(StrEnum):
    PAID = "PAID"
    PENDING = "PENDING"
    OVERDUE = "OVERDUE"
    FAILED = "FAILED"
    WRITTEN_OFF = "WRITTEN_OFF"


class TicketPriority(StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class TicketStatus(StrEnum):
    OPEN = "OPEN"
    PENDING = "PENDING"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    ESCALATED = "ESCALATED"


class DocumentSourceType(StrEnum):
    CUSTOMER_EMAIL = "CUSTOMER_EMAIL"
    CSM_NOTE = "CSM_NOTE"
    QBR_NOTE = "QBR_NOTE"
    RENEWAL_NOTE = "RENEWAL_NOTE"
    MEETING_SUMMARY = "MEETING_SUMMARY"
    ONBOARDING_NOTE = "ONBOARDING_NOTE"
    SUPPORT_SUMMARY = "SUPPORT_SUMMARY"


class CustomerOutcome(StrEnum):
    CHURNED = "CHURNED"
    RENEWED = "RENEWED"
    DOWNGRADED = "DOWNGRADED"
    EXPANDED = "EXPANDED"
    UNKNOWN = "UNKNOWN"


class RiskLevel(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class RunStatus(StrEnum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    RETRYING = "RETRYING"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @property
    def is_terminal(self) -> bool:
        return self in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}


class TaskStatus(StrEnum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    RETRYING = "RETRYING"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    SKIPPED = "SKIPPED"

    @property
    def is_terminal(self) -> bool:
        return self in {
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.SKIPPED,
        }


class AgentType(StrEnum):
    PLANNER = "planner"
    DATA = "data"
    RISK = "risk"
    RETRIEVAL = "retrieval"
    INVESTIGATOR = "investigator"
    VERIFIER = "verifier"
    REPORTER = "reporter"
    POLICY = "policy"
    SYSTEM = "system"


class WorkflowType(StrEnum):
    CHURN_INVESTIGATION = "churn_investigation"


class WorkflowMode(StrEnum):
    """How much human control the operator asked for."""

    STANDARD = "STANDARD"  # deterministic approval policy applies
    REVIEW_ALL = "REVIEW_ALL"  # every recommended action needs approval
    READ_ONLY = "READ_ONLY"  # no write actions proposed at all


class ClaimType(StrEnum):
    OBSERVED_FACT = "OBSERVED_FACT"
    CALCULATED_METRIC = "CALCULATED_METRIC"
    INFERENCE = "INFERENCE"


class ClaimStatus(StrEnum):
    PENDING = "PENDING"
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    CONTRADICTED = "CONTRADICTED"

    @property
    def usable_as_fact(self) -> bool:
        return self is ClaimStatus.SUPPORTED


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ActionType(StrEnum):
    """Recommended-action catalogue.

    ``requires_approval`` is deterministic application logic — an LLM selects an
    action type, it never decides whether the action is sensitive.
    """

    # Read-only / internal
    INTERNAL_REVIEW = "INTERNAL_REVIEW"
    SCHEDULE_INTERNAL_MEETING = "SCHEDULE_INTERNAL_MEETING"
    MONITOR_USAGE = "MONITOR_USAGE"
    PREPARE_BRIEFING = "PREPARE_BRIEFING"
    ASSIGN_OWNER = "ASSIGN_OWNER"
    # Sensitive / external side effects
    SEND_CUSTOMER_EMAIL = "SEND_CUSTOMER_EMAIL"
    OFFER_DISCOUNT = "OFFER_DISCOUNT"
    UPDATE_CRM_RECORD = "UPDATE_CRM_RECORD"
    CHANGE_SUBSCRIPTION = "CHANGE_SUBSCRIPTION"
    ESCALATE_TO_EXECUTIVE = "ESCALATE_TO_EXECUTIVE"
    SCHEDULE_CUSTOMER_CALL = "SCHEDULE_CUSTOMER_CALL"

    @property
    def is_sensitive(self) -> bool:
        return self in SENSITIVE_ACTIONS


SENSITIVE_ACTIONS: frozenset[ActionType] = frozenset(
    {
        ActionType.SEND_CUSTOMER_EMAIL,
        ActionType.OFFER_DISCOUNT,
        ActionType.UPDATE_CRM_RECORD,
        ActionType.CHANGE_SUBSCRIPTION,
        ActionType.ESCALATE_TO_EXECUTIVE,
        ActionType.SCHEDULE_CUSTOMER_CALL,
    }
)


class ToolAccess(StrEnum):
    READ_ONLY = "READ_ONLY"
    SENSITIVE_WRITE = "SENSITIVE_WRITE"


class EvidenceSourceType(StrEnum):
    DOCUMENT_CHUNK = "DOCUMENT_CHUNK"
    SUPPORT_TICKET = "SUPPORT_TICKET"
    NPS_SURVEY = "NPS_SURVEY"
    USAGE_METRIC = "USAGE_METRIC"
    PAYMENT_RECORD = "PAYMENT_RECORD"
    SUBSCRIPTION = "SUBSCRIPTION"


class ActorType(StrEnum):
    SYSTEM = "SYSTEM"
    AGENT = "AGENT"
    HUMAN = "HUMAN"
    WORKER = "WORKER"


class AuditEventType(StrEnum):
    RUN_CREATED = "RUN_CREATED"
    RUN_STARTED = "RUN_STARTED"
    RUN_COMPLETED = "RUN_COMPLETED"
    RUN_FAILED = "RUN_FAILED"
    RUN_CANCELLED = "RUN_CANCELLED"
    PLAN_CREATED = "PLAN_CREATED"
    PLAN_REJECTED = "PLAN_REJECTED"
    TASK_QUEUED = "TASK_QUEUED"
    TASK_STARTED = "TASK_STARTED"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_RETRYING = "TASK_RETRYING"
    TASK_FAILED = "TASK_FAILED"
    TASK_SKIPPED = "TASK_SKIPPED"
    TOOL_CALLED = "TOOL_CALLED"
    LLM_CALLED = "LLM_CALLED"
    EVIDENCE_RECORDED = "EVIDENCE_RECORDED"
    CLAIM_RECORDED = "CLAIM_RECORDED"
    CLAIM_VERIFIED = "CLAIM_VERIFIED"
    INVESTIGATION_COMPLETED = "INVESTIGATION_COMPLETED"
    REPORT_GENERATED = "REPORT_GENERATED"
    APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
    APPROVAL_GRANTED = "APPROVAL_GRANTED"
    APPROVAL_REJECTED = "APPROVAL_REJECTED"
    PROMPT_INJECTION_DETECTED = "PROMPT_INJECTION_DETECTED"
    VALIDATION_FAILED = "VALIDATION_FAILED"


class EvaluationStatus(StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
