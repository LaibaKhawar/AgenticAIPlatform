"""Time access.

A single place that produces "now". Everything timezone-aware, and a seam the
tests can freeze instead of depending on the real calendar.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

_frozen: datetime | None = None


def utcnow() -> datetime:
    return _frozen or datetime.now(tz=UTC)


def today() -> date:
    return utcnow().date()


def freeze(moment: datetime | None) -> None:
    """Pin the clock (tests only). ``freeze(None)`` restores real time."""
    global _frozen
    if moment is not None and moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    _frozen = moment
