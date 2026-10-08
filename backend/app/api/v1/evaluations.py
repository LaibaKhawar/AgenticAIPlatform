"""Evaluation endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import DbSession, Pagination, parse_uuid
from app.core.config import get_settings
from app.core.logging import get_logger
from app.evaluation.runner import EvaluationParameters, create_evaluation, execute_evaluation
from app.models.workflow import EvaluationRun
from app.schemas.api import EvaluationRequest, EvaluationResponse, Page

logger = get_logger(__name__)
router = APIRouter(prefix="/evaluations", tags=["evaluation"])


@router.post(
    "/run",
    response_model=EvaluationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Run the evaluation harness",
)
def run_evaluation(payload: EvaluationRequest, session: DbSession) -> EvaluationResponse:
    parameters = EvaluationParameters(
        name=payload.name,
        sample_size=payload.sample_size,
        retrieval_sample=payload.retrieval_sample,
        include_workflow_metrics=payload.include_workflow_metrics,
    )
    record = create_evaluation(session, parameters)
    evaluation_id = record.id
    session.commit()

    if payload.run_async and get_settings().workflow_executor == "celery":
        from app.workers.tasks import run_evaluation_task

        run_evaluation_task.apply_async(args=[str(evaluation_id)])
        logger.info("evaluation dispatched to worker", extra={"evaluation_id": str(evaluation_id)})
    else:
        # Synchronous by default: the harness takes a few seconds on the
        # synthetic dataset and an operator expects numbers back immediately.
        execute_evaluation(evaluation_id)

    session.expire_all()
    refreshed = session.get(EvaluationRun, evaluation_id)
    assert refreshed is not None
    return EvaluationResponse.model_validate(refreshed)


@router.get("", response_model=Page[EvaluationResponse], summary="List evaluation runs")
def list_evaluations(session: DbSession, page: Pagination) -> Page[EvaluationResponse]:
    from sqlalchemy import func

    rows = list(
        session.scalars(
            select(EvaluationRun).order_by(EvaluationRun.created_at.desc()).limit(page.limit).offset(page.offset)
        )
    )
    total = int(session.scalar(select(func.count()).select_from(EvaluationRun)) or 0)
    return Page[EvaluationResponse](
        items=[EvaluationResponse.model_validate(row) for row in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/latest", response_model=EvaluationResponse | None, summary="Most recent evaluation")
def latest_evaluation(session: DbSession) -> EvaluationResponse | None:
    row = session.scalars(select(EvaluationRun).order_by(EvaluationRun.created_at.desc()).limit(1)).first()
    return EvaluationResponse.model_validate(row) if row else None


@router.get("/{evaluation_id}", response_model=EvaluationResponse, summary="One evaluation run")
def get_evaluation(evaluation_id: str, session: DbSession) -> EvaluationResponse:
    record = session.get(EvaluationRun, parse_uuid(evaluation_id, field="evaluation id"))
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "not_found", "message": "No such evaluation run."}},
        )
    return EvaluationResponse.model_validate(record)
