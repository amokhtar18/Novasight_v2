"""Worker observability: job metrics + tracing (Phase 6.4).

Background-job metrics use Dramatiq's built-in Prometheus middleware, which is
**fork-safe** — it manages ``PROMETHEUS_MULTIPROC_DIR`` across the worker's forked
processes and serves aggregated metrics from one embedded HTTP server. We only have
to point its host/port at our settings (it reads ``dramatiq_prom_host`` /
``dramatiq_prom_port`` from the environment at import, so they must be set *before*
the middleware module is imported).

Tracing reuses the same OTLP setup as the API; httpx + SQLAlchemy auto-instrumentation
then produce spans for the outbound and database calls a job makes.
"""
from __future__ import annotations

import logging
import os

import dramatiq

from app.core.config import Settings, get_settings
from app.core.tracing import configure_tracing

logger = logging.getLogger(__name__)


def setup_worker_observability(
    settings: Settings | None = None, *, service_name: str = "novasight-worker"
) -> None:
    """Wire worker metrics (Dramatiq Prometheus middleware) + tracing.

    Call once in the worker entrypoint, after the broker is configured and before the
    actor modules are imported.
    """
    settings = settings or get_settings()
    obs = settings.observability

    configure_tracing(settings, service_name=service_name)

    if not obs.metrics_enabled:
        return

    # Set the exposition host/port BEFORE importing the middleware (it reads them at
    # module import). Then add it to the already-configured global broker.
    # These env var names are lowercase by Dramatiq's contract — do not capitalize.
    # Bind on all interfaces so the metrics port is scrapable inside the container.
    os.environ.setdefault("dramatiq_prom_host", "0.0.0.0")  # noqa: S104
    os.environ["dramatiq_prom_port"] = str(obs.worker_metrics_port)  # noqa: SIM112

    from dramatiq.middleware.prometheus import Prometheus

    dramatiq.get_broker().add_middleware(Prometheus())
    logger.info("worker metrics enabled on :%d", obs.worker_metrics_port)
