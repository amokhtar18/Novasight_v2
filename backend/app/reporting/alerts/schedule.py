"""periodiq dispatcher — enqueue due KPI evaluations on each heartbeat.

periodiq fires ``dispatch_due_kpis`` on the configured heartbeat cron
(``ALERTS__DISPATCH_CRON``). The dispatcher scans the KPI registry and enqueues an
``evaluate_kpi`` job for each KPI whose own cron schedule is due — keeping per-KPI
schedules as tenant config in the database. Each enqueued job re-resolves and
enforces its own tenant scope before touching tenant data.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import dramatiq
from periodiq import cron as periodiq_cron

from app.core.config import get_settings
from app.core.db import session_scope
from app.reporting.alerts.actors import evaluate_kpi
from app.reporting.alerts.service import list_enabled_kpis, select_due


async def _dispatch(now: datetime) -> None:
    """Enqueue an evaluation job for every KPI due at ``now``."""
    async with session_scope() as db:
        kpis = await list_enabled_kpis(db)
        for kpi_id in select_due(kpis, now):
            evaluate_kpi.send(str(kpi_id))


@dramatiq.actor(periodic=periodiq_cron(get_settings().alerts.dispatch_cron))
def dispatch_due_kpis() -> None:
    """periodiq heartbeat: find and enqueue all KPIs due at this minute."""
    asyncio.run(_dispatch(datetime.now(tz=UTC)))
