"""API v1 router assembly."""

from fastapi import APIRouter, Depends

from app.api.deps import require_api_key
from app.api.v1 import approvals, customers, dashboard, evaluations, runs

api_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])
api_router.include_router(customers.router)
api_router.include_router(runs.router)
api_router.include_router(approvals.router)
api_router.include_router(evaluations.router)
api_router.include_router(dashboard.router)

__all__ = ["api_router"]
