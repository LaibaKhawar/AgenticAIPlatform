"""Shared API dependencies: auth boundary, pagination, id parsing."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.schemas.api import PaginationParams

DbSession = Annotated[Session, Depends(get_db)]


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Pragmatic development/demo auth boundary.

    When ``API_KEY`` is unset the API is open, which is the right default for a
    local demo. When it is set, every ``/api/v1`` request must present it. The
    dependency is attached at router level so production authentication (OIDC,
    session cookies, per-tenant keys) replaces one function rather than touching
    every endpoint.
    """
    settings = get_settings()
    if not settings.api_key:
        return
    if x_api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "unauthorized", "message": "A valid X-API-Key is required."}},
            headers={"WWW-Authenticate": "ApiKey"},
        )


def pagination(
    limit: Annotated[int, Query(ge=1, le=500, description="Page size")] = 25,
    offset: Annotated[int, Query(ge=0, le=1_000_000, description="Rows to skip")] = 0,
) -> PaginationParams:
    return PaginationParams(limit=limit, offset=offset)


Pagination = Annotated[PaginationParams, Depends(pagination)]


def parse_uuid(value: str, *, field: str = "id") -> uuid.UUID:
    """Return a 404 for a malformed id rather than a 500."""
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "not_found",
                    "message": f"'{value}' is not a valid {field}.",
                }
            },
        ) from error


def db_session() -> Iterator[Session]:
    yield from get_db()
