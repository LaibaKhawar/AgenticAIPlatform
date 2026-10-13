"""The stack probe reports what is installed and reachable — never a guess."""

from __future__ import annotations

from importlib import metadata

import pytest

from app.core import stack
from app.core.config import get_settings

pytestmark = pytest.mark.unit


def test_library_versions_match_the_installed_distributions() -> None:
    versions = stack.library_versions()
    assert versions["fastapi"] == metadata.version("fastapi")
    assert versions["sqlalchemy"] == metadata.version("SQLAlchemy")
    assert versions["celery"] == metadata.version("celery")


def test_a_missing_distribution_is_reported_as_none_not_guessed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stack, "LIBRARIES", {"ghost": "veriflow-no-such-distribution"})
    assert stack.library_versions() == {"ghost": None}


def test_unreachable_redis_is_reported_rather_than_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    # Port 1 is reserved and closed: the connection is refused immediately.
    monkeypatch.setattr(get_settings(), "redis_url", "redis://127.0.0.1:1/0")
    assert stack.redis_version() == {"reachable": False, "version": None}
