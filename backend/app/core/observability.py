"""Wire metrics + tracing into the FastAPI app (Phase 6.4).

Called once at import from ``app.main``. Metrics are always wired (cheap, and the
scrape endpoint is harmless when unused); tracing is a no-op unless configured. Doing
this at import — not in the lifespan — ensures the middleware/instrumentation are in
the ASGI stack before the app starts serving.
"""
from __future__ import annotations

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import get_settings
from app.core.metrics import PrometheusHTTPMiddleware, render_latest
from app.core.tracing import configure_tracing, instrument_fastapi


def setup_fastapi_observability(app: FastAPI, *, service_name: str = "analytica-api") -> None:
    """Add the metrics middleware + ``/metrics`` route and configure tracing."""
    settings = get_settings()
    obs = settings.observability

    # Tracing: provider/exporter, then instrument the app for server spans. Both are
    # no-ops unless OBSERVABILITY__TRACING_ENABLED + OTLP endpoint are set.
    configure_tracing(settings, service_name=service_name)
    instrument_fastapi(app, settings)

    if obs.metrics_enabled:
        app.add_middleware(PrometheusHTTPMiddleware)

        async def _metrics(_request: Request) -> Response:
            return render_latest()

        # Conventional, unauthenticated scrape endpoint.
        app.add_route(obs.metrics_path, _metrics, methods=["GET"], include_in_schema=False)
