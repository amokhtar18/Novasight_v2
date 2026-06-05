"""Dramatiq broker seam — the background-job boundary.

All background work (scheduled reports in Phase 5, KPI alerts later) runs through
a Dramatiq broker backed by the **same Redis the app already uses**. Connection
parameters come from ``RedisSettings`` (golden rule 1: no hardcoded
infrastructure) — never a literal URL.

The broker is process-wide: built once from settings and registered as the global
Dramatiq broker so ``@dramatiq.actor`` decorators bind to it. The FastAPI request
path never imports this module; only the worker entrypoint and code that *enqueues*
a message (``actor.send(...)``) touches it.

``configure_broker`` is idempotent and safe to call at import time in the worker
entrypoint. Tests substitute an in-memory ``StubBroker`` by setting it as the
global broker before importing the actors module.
"""
from __future__ import annotations

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from periodiq import PeriodiqMiddleware

from app.core.config import RedisSettings, Settings, get_settings

_broker: RedisBroker | None = None


def redis_url(cfg: RedisSettings) -> str:
    """Build the Redis connection URL from settings (no literal hosts anywhere)."""
    return f"redis://{cfg.host}:{cfg.port}/{cfg.db}"


def configure_broker(settings: Settings | None = None) -> RedisBroker:
    """Build (once) the Redis-backed broker and register it as the global broker.

    Idempotent: repeated calls return the same broker. ``settings`` is injectable
    for tests; in production it is read from the environment via ``get_settings``.
    """
    global _broker
    if _broker is None:
        cfg = (settings or get_settings()).redis
        # RedisBroker.__init__ is untyped in dramatiq; the call is otherwise sound.
        _broker = RedisBroker(url=redis_url(cfg))  # type: ignore[no-untyped-call]
        # Register periodiq's middleware so ``@actor(periodic=...)`` is a valid option
        # (the dispatcher heartbeat in app/reporting/schedule.py uses it).
        _broker.add_middleware(PeriodiqMiddleware())
        dramatiq.set_broker(_broker)
    return _broker
