"""Dramatiq actor for ETL pipeline runs (#3).

Importing this module requires a configured broker — the worker entrypoint calls
``configure_broker`` first; the service enqueues lazily (importing this only when it
actually sends), and tests set a ``StubBroker`` before importing. The actor is a thin
bridge from Dramatiq's synchronous model to the async ``PipelineExecutor`` (all logic
lives in ``pipeline_executor.py`` and is tested there directly).
"""
from __future__ import annotations

import asyncio
import uuid

import dramatiq

from app.core.db import session_scope
from app.ingestion.pipeline_executor import build_pipeline_executor

# Dedicated queue so ETL workers scale independently of reports/alerts.
ETL_QUEUE = "etl"


async def _run_pipeline(run_id: str) -> None:
    """Async body: execute one pipeline run within a job-scoped DB session."""
    executor = build_pipeline_executor()
    async with session_scope() as db:
        await executor.execute(db, uuid.UUID(run_id))


@dramatiq.actor(queue_name=ETL_QUEUE, max_retries=0)
def run_pipeline(run_id: str) -> None:
    """Execute one pipeline run. Enqueue with ``run_pipeline.send(str(run_id))``.

    ``max_retries=0``: a failed run is recorded as ``error`` on the row and re-run
    explicitly by the user, rather than silently retried (which could surprise on a
    non-idempotent source).
    """
    asyncio.run(_run_pipeline(run_id))
