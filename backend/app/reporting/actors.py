"""Dramatiq actors for scheduled reporting.

Importing this module requires a configured broker — the worker entrypoint calls
``configure_broker`` first; tests set a ``StubBroker`` as the global broker before
importing. The actors are deliberately thin: they bridge Dramatiq's synchronous
execution model to the async report service via ``asyncio.run`` and hold no
business logic (that lives in ``service.py`` and is tested there directly).
"""
from __future__ import annotations

import asyncio
import uuid

import dramatiq

from app.core.db import session_scope
from app.reporting.service import build_report_service

# Queue name for report jobs; a dedicated queue lets ops scale report workers
# independently of other background work.
REPORTS_QUEUE = "reports"


async def _render_and_send(report_id: str) -> None:
    """Async body: assemble the service and run one report within a job session."""
    service = build_report_service()
    async with session_scope() as db:
        await service.run_report(db, uuid.UUID(report_id))


@dramatiq.actor(queue_name=REPORTS_QUEUE, max_retries=3)
def render_and_send_report(report_id: str) -> None:
    """Render and email one report. Enqueue with ``render_and_send_report.send(id)``."""
    asyncio.run(_render_and_send(report_id))
