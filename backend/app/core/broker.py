"""Dramatiq broker seam — the background-job boundary.

All background work (scheduled reports in Phase 5, KPI alerts later) runs through
a Dramatiq broker backed by the **same Redis the app already uses**. Connection
parameters come from ``RedisSettings`` (golden rule 1: no hardcoded
infrastructure) — never a literal URL.

The broker is process-wide: built once from settings and registered as the global
Dramatiq broker so ``@dramatiq.actor`` decorators bind to it. Both the worker
entrypoint and the API call ``configure_broker`` at startup — the API enqueues from
the request path (e.g. pipeline run-now via ``actor.send(...)``), and without a
configured global broker dramatiq falls back to a default broker pointing at
``localhost:6379``, which 500s the enqueue.

``configure_broker`` is idempotent and safe to call at import time in the worker
entrypoint / the API lifespan. It must run before any actor module is imported, since
``@dramatiq.actor`` binds to whatever the global broker is at import time. Tests
substitute an in-memory ``StubBroker`` by setting it as the global broker before
importing the actors module.
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
