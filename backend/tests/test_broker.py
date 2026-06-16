"""Tests for the Dramatiq broker seam (``app.core.broker``).

Regression guard for the run-now 500: enqueuing from the API request path
(``run_pipeline.send(...)``) requires the global broker to be configured from
settings. Without it, dramatiq falls back to a default ``RedisBroker()`` pointing at
``localhost:6379`` and the enqueue raises ConnectionRefused -> HTTP 500. So we assert
``configure_broker`` builds the broker from the settings Redis URL (not the default).
"""
from __future__ import annotations

from typing import Any

import dramatiq
import pytest

from app.core import broker as broker_mod
from app.core.config import RedisSettings, Settings


class _RecordingBroker:
    """Stand-in for ``RedisBroker`` that records its URL and never connects."""

    def __init__(self, *, url: str) -> None:
        self.url = url
        self.middleware: list[Any] = []

    def add_middleware(self, mw: Any) -> None:
        self.middleware.append(mw)

    # dramatiq.set_broker only stores the object; no Broker interface needed here.


@pytest.fixture()
def _reset_broker() -> Any:
    """Clear the module + dramatiq global broker around each test (both are global)."""
    saved = dramatiq.broker.global_broker
    broker_mod._broker = None
    yield
    broker_mod._broker = None
    dramatiq.broker.global_broker = saved


def test_redis_url_is_built_from_settings() -> None:
    cfg = RedisSettings(host="redis", port=6380, db=3)
    assert broker_mod.redis_url(cfg) == "redis://redis:6380/3"


def test_configure_broker_uses_settings_host_not_localhost(
    monkeypatch: pytest.MonkeyPatch, _reset_broker: None
) -> None:
    captured: list[str] = []

    def _factory(*, url: str) -> _RecordingBroker:
        captured.append(url)
        return _RecordingBroker(url=url)

    monkeypatch.setattr(broker_mod, "RedisBroker", _factory)

    settings = Settings.model_construct(redis=RedisSettings(host="redis", port=6379, db=0))
    result = broker_mod.configure_broker(settings)

    # Built from settings (the bug: a default RedisBroker() points at localhost:6379).
    assert captured == ["redis://redis:6379/0"]
    assert result.url == "redis://redis:6379/0"  # type: ignore[attr-defined]
    # Registered as the process-wide broker so request-path .send() targets it.
    assert dramatiq.get_broker() is result


def test_configure_broker_is_idempotent(
    monkeypatch: pytest.MonkeyPatch, _reset_broker: None
) -> None:
    builds: list[str] = []
    monkeypatch.setattr(
        broker_mod, "RedisBroker", lambda *, url: (builds.append(url), _RecordingBroker(url=url))[1]
    )

    settings = Settings.model_construct(redis=RedisSettings(host="redis", port=6379, db=0))
    first = broker_mod.configure_broker(settings)
    second = broker_mod.configure_broker(settings)

    assert first is second
    assert len(builds) == 1  # built once, not on every call
