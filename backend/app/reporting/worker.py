"""Reporting worker entrypoint.

Run the worker with::

    dramatiq app.reporting.worker

and the scheduler with::

    periodiq app.reporting.worker

Both load this module, which first wires the Dramatiq broker from settings and then
imports the actor modules so their ``@dramatiq.actor`` declarations register against
that broker. The broker MUST be configured before the actor modules are imported,
hence the deliberate import order below.
"""
from __future__ import annotations

from app.core.broker import configure_broker
from app.core.db import use_null_pool
from app.reporting.observability import setup_worker_observability

# Each actor runs its async body in its own ``asyncio.run`` (a fresh event loop per
# job). asyncpg connections are loop-bound, so the engine must not pool them across
# jobs — disable pooling for this process before any session is opened. See
# ``app.core.db.use_null_pool``.
use_null_pool()

configure_broker()

# Metrics (Dramatiq's fork-safe Prometheus middleware) + tracing. Wired after the
# broker exists and before the actor modules are imported.
setup_worker_observability()

# Import after the broker is set so actor registration binds to it. This single
# worker entrypoint hosts reporting (5.1), KPI-alert (5.2), and ETL pipeline (#3/#4)
# actors/schedules.
from app.ingestion import actors as etl_actors  # noqa: E402
from app.ingestion import scheduler as etl_scheduler  # noqa: E402
from app.reporting import actors, schedule  # noqa: E402
from app.reporting.alerts import actors as alert_actors  # noqa: E402
from app.reporting.alerts import schedule as alert_schedule  # noqa: E402

__all__ = [
    "actors",
    "alert_actors",
    "alert_schedule",
    "etl_actors",
    "etl_scheduler",
    "schedule",
]
