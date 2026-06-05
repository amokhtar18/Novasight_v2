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
from app.reporting.observability import setup_worker_observability

configure_broker()

# Metrics (Dramatiq's fork-safe Prometheus middleware) + tracing. Wired after the
# broker exists and before the actor modules are imported.
setup_worker_observability()

# Import after the broker is set so actor registration binds to it. This single
# worker entrypoint hosts both reporting (5.1) and KPI-alert (5.2) actors/schedules.
from app.reporting import actors, schedule  # noqa: E402
from app.reporting.alerts import actors as alert_actors  # noqa: E402
from app.reporting.alerts import schedule as alert_schedule  # noqa: E402

__all__ = ["actors", "alert_actors", "alert_schedule", "schedule"]
