"""periodiq dispatcher — enqueue due reports on each heartbeat.

periodiq fires ``dispatch_due_reports`` on the configured heartbeat cron
(``REPORTING__DISPATCH_CRON``, every minute by default). The dispatcher then scans
the report registry and enqueues a ``render_and_send_report`` job for each report
whose *own* cron schedule is due — keeping per-report schedules as tenant config in
the database rather than as code-level periodic actors.

The scan reads only control-plane schedule metadata; every enqueued job
re-resolves and enforces its own tenant scope before touching tenant data.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import dramatiq
from periodiq import cron as periodiq_cron

from app.core.config import get_settings
from app.core.db import session_scope
from app.reporting.actors import render_and_send_report
from app.reporting.service import list_enabled_reports, select_due


async def _dispatch(now: datetime) -> None:
    """Enqueue a render job for every report due at ``now``."""
    async with session_scope() as db:
        reports = await list_enabled_reports(db)
        for report_id in select_due(reports, now):
            render_and_send_report.send(str(report_id))


@dramatiq.actor(periodic=periodiq_cron(get_settings().reporting.dispatch_cron))
def dispatch_due_reports() -> None:
    """periodiq heartbeat: find and enqueue all reports due at this minute."""
    asyncio.run(_dispatch(datetime.now(tz=UTC)))
