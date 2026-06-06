"""Prometheus metrics — the one place metric series are defined (Phase 6.4).

Three families, all on the default registry (which also ships the process/platform
**resource** collectors — CPU, memory, fds — so ``/metrics`` exposes resource metrics
for free):

* HTTP request metrics (count + latency) via :class:`PrometheusHTTPMiddleware`.
* Pipeline metrics (rows ingested + ingest duration) recorded by the ingestion path.

Background-job (worker) metrics come from Dramatiq's built-in, fork-safe Prometheus
middleware (see ``app.reporting.observability``), so they are not redefined here.

No infrastructure or tenant values are hardcoded, and labels deliberately exclude the
tenant id to avoid unbounded cardinality and keep tenant identity out of a shared
scrape endpoint (tenancy-isolation: no cross-tenant leakage).
"""
from __future__ import annotations

import time

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# --- HTTP (API) -------------------------------------------------------------

HTTP_REQUESTS = Counter(
    "novasight_http_requests_total",
    "Total HTTP requests.",
    labelnames=("method", "path", "status"),
)
HTTP_REQUEST_DURATION = Histogram(
    "novasight_http_request_duration_seconds",
    "HTTP request latency in seconds.",
    labelnames=("method", "path"),
)

# --- Pipeline (ingestion) ---------------------------------------------------

INGEST_ROWS = Counter(
    "novasight_ingest_rows_total",
    "Rows written by the ingestion pipeline.",
    labelnames=("status",),
)
INGEST_DURATION = Histogram(
    "novasight_ingest_duration_seconds",
    "Ingestion pipeline run duration in seconds.",
    labelnames=("status",),
)


def render_latest() -> Response:
    """Return the current metrics as a Prometheus-format HTTP response."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def _route_template(request: Request) -> str:
    """The matched route template (low cardinality), falling back to the raw path.

    Using the template (e.g. ``/api/v1/tenants/{slug}``) instead of the concrete
    path keeps the ``path`` label bounded.
    """
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str):
        return path
    return request.url.path


class PrometheusHTTPMiddleware:
    """Pure-ASGI middleware recording request count + latency per matched route.

    ASGI (not ``BaseHTTPMiddleware``) so it composes cleanly with the OpenTelemetry
    ASGI instrumentation without interfering with streaming responses.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        start = time.perf_counter()
        status_holder = {"code": 500}

        async def _send(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["code"] = message["status"]
            await send(message)

        try:
            await self._app(scope, receive, _send)
        finally:
            request = Request(scope)
            path = _route_template(request)
            method = scope.get("method", "GET")
            elapsed = time.perf_counter() - start
            HTTP_REQUESTS.labels(method=method, path=path, status=status_holder["code"]).inc()
            HTTP_REQUEST_DURATION.labels(method=method, path=path).observe(elapsed)
