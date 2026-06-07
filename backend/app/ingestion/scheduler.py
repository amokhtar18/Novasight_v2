"""periodiq dispatcher — enqueue due pipeline runs on each heartbeat (#4).

periodiq fires ``dispatch_due_pipelines`` on the configured heartbeat cron
(``PIPELINE_DISPATCH_CRON``, every minute by default). The dispatcher scans the
schedule registry and, for each enabled pipeline schedule whose own cron is due,
records a queued run and enqueues ``run_pipeline`` — the same worker path as run-now.

Importing this module requires a configured broker (the worker entrypoint sets it;
tests set a ``StubBroker`` first). The due-selection + run-creation logic lives in
``ScheduleService.create_due_runs`` and is unit-tested there directly.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import dramatiq
from periodiq import cron as periodiq_cron

from app.core.config import get_settings
from app.core.db import session_scope
from app.ingestion.actors import run_pipeline
from app.services.schedules import ScheduleService


def _enqueue(run_id: str) -> None:
    """Enqueue one pipeline run (typed to return ``None`` for the dispatcher)."""
    run_pipeline.send(run_id)


async def _dispatch(now: datetime) -> None:
    """Create + enqueue a run for every pipeline schedule due at ``now``."""
    async with session_scope() as db:
        await ScheduleService(db).create_due_runs(now, _enqueue)


@dramatiq.actor(periodic=periodiq_cron(get_settings().pipeline_dispatch_cron))
def dispatch_due_pipelines() -> None:
    """periodiq heartbeat: find and enqueue all pipeline runs due at this minute."""
    asyncio.run(_dispatch(datetime.now(tz=UTC)))
