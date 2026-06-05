"""Dramatiq actors for KPI alerts.

Importing this module requires a configured broker (the worker entrypoint sets it
first; tests use a ``StubBroker``). Thin glue: bridges sync Dramatiq to the async
alert service via ``asyncio.run``; the breach logic lives in ``service.py``.
"""
from __future__ import annotations

import asyncio
import uuid

import dramatiq

from app.core.db import session_scope
from app.reporting.alerts.service import build_kpi_alert_service

# Dedicated queue so KPI evaluation can be scaled independently of report rendering.
ALERTS_QUEUE = "alerts"


async def _evaluate(kpi_id: str) -> None:
    """Async body: evaluate one KPI within a committing job session.

    The session commits on success so any breach-state transition is persisted —
    that persistence is what makes alerting exactly-once across ticks.
    """
    service = build_kpi_alert_service()
    async with session_scope() as db:
        await service.evaluate(db, uuid.UUID(kpi_id))


@dramatiq.actor(queue_name=ALERTS_QUEUE, max_retries=3)
def evaluate_kpi(kpi_id: str) -> None:
    """Evaluate one KPI threshold. Enqueue with ``evaluate_kpi.send(kpi_id)``.

    Dagster asset-check events (Phase 2) can enqueue this directly to evaluate a KPI
    the moment its underlying asset is refreshed, in addition to the cron schedule.
    """
    asyncio.run(_evaluate(kpi_id))
