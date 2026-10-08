"""Approval endpoints — the human-in-the-loop boundary."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import DbSession, Pagination, parse_uuid
from app.api.v1.runs import _approval_item
from app.core.logging import get_logger
from app.models.enums import ActorType, ApprovalStatus, AuditEventType, RunStatus
from app.orchestration.engine import get_engine
from app.repositories.investigations import ApprovalRepository
from app.repositories.runs import RunRepository
from app.schemas.api import ApprovalDecisionRequest, ApprovalResponse, Page

logger = get_logger(__name__)
router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("", response_model=Page[ApprovalResponse], summary="List approval requests")
def list_approvals(
    session: DbSession,
    page: Pagination,
    approval_status: Annotated[ApprovalStatus | None, Query(alias="status")] = ApprovalStatus.PENDING,
    run_id: Annotated[str | None, Query()] = None,
) -> Page[ApprovalResponse]:
    repository = ApprovalRepository(session)
    parsed = parse_uuid(run_id, field="run id") if run_id else None
    approvals = repository.list_approvals(status=approval_status, run_id=parsed, limit=page.limit, offset=page.offset)
    return Page[ApprovalResponse](
        items=[_approval_item(session, approval) for approval in approvals],
        total=repository.count_approvals(status=approval_status, run_id=parsed),
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{approval_id}", response_model=ApprovalResponse, summary="One approval request")
def get_approval(approval_id: str, session: DbSession) -> ApprovalResponse:
    approval = ApprovalRepository(session).get(parse_uuid(approval_id, field="approval id"))
    if approval is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "not_found", "message": "No such approval request."}},
        )
    return _approval_item(session, approval)


def _decide(
    session: DbSession,
    approval_id: str,
    payload: ApprovalDecisionRequest,
    *,
    decision: ApprovalStatus,
) -> ApprovalResponse:
    repository = ApprovalRepository(session)
    parsed = parse_uuid(approval_id, field="approval id")
    approval = repository.get(parsed, for_update=True)
    if approval is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "not_found", "message": "No such approval request."}},
        )
    if approval.status != ApprovalStatus.PENDING.value:
        # Idempotent-ish: a repeated decision is a conflict, not a silent
        # overwrite of someone else's review.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "already_resolved",
                    "message": (
                        f"This request was already {approval.status.lower()} by "
                        f"{approval.reviewed_by or 'another reviewer'}."
                    ),
                    "details": {
                        "status": approval.status,
                        "reviewed_at": approval.reviewed_at.isoformat() if approval.reviewed_at else None,
                    },
                }
            },
        )

    run_repository = RunRepository(session)
    run = run_repository.get(approval.run_id)
    if run is not None and RunStatus(run.status) in {RunStatus.CANCELLED, RunStatus.FAILED}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "conflict",
                    "message": f"The parent run is {run.status}; approvals can no longer be applied.",
                }
            },
        )

    repository.resolve(approval, status=decision, reviewed_by=payload.reviewed_by, comment=payload.comment)
    run_repository.record_event(
        run_id=approval.run_id,
        customer_id=approval.customer_id,
        event_type=(
            AuditEventType.APPROVAL_GRANTED if decision is ApprovalStatus.APPROVED else AuditEventType.APPROVAL_REJECTED
        ),
        actor_type=ActorType.HUMAN,
        actor_id=payload.reviewed_by,
        message=(
            f"{approval.action_type} "
            f"{'approved' if decision is ApprovalStatus.APPROVED else 'rejected'} by "
            f"{payload.reviewed_by}."
        ),
        payload={
            "approval_id": str(approval.id),
            "action_type": approval.action_type,
            "comment": payload.comment,
        },
    )

    response = _approval_item(session, approval)
    run_id = approval.run_id
    session.commit()

    # Resuming opens its own transaction and is a no-op while other requests
    # for the same run are still pending.
    get_engine().resume_after_approval(run_id)
    logger.info(
        "approval resolved",
        extra={
            "approval_id": approval_id,
            "decision": decision.value,
            "reviewed_by": payload.reviewed_by,
            "run_id": str(run_id),
        },
    )
    return response


@router.post("/{approval_id}/approve", response_model=ApprovalResponse, summary="Approve a sensitive action")
def approve(approval_id: str, payload: ApprovalDecisionRequest, session: DbSession) -> ApprovalResponse:
    return _decide(session, approval_id, payload, decision=ApprovalStatus.APPROVED)


@router.post("/{approval_id}/reject", response_model=ApprovalResponse, summary="Reject a sensitive action")
def reject(approval_id: str, payload: ApprovalDecisionRequest, session: DbSession) -> ApprovalResponse:
    return _decide(session, approval_id, payload, decision=ApprovalStatus.REJECTED)
