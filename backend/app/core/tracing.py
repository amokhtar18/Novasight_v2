"""OpenTelemetry tracing setup (Phase 6.4).

One ``configure_tracing`` call per process builds a ``TracerProvider`` exporting spans
over OTLP/HTTP to the configured collector, and turns on auto-instrumentation for
outbound HTTP (httpx) and the database (SQLAlchemy). The API additionally instruments
the ASGI app (``instrument_fastapi``), so a single request produces an end-to-end span
tree: server span → DB spans → outbound spans.

Everything is config-driven (golden rule 1): the collector endpoint comes from
``OBSERVABILITY__OTLP_ENDPOINT`` and tracing stays a no-op until it is set and
``OBSERVABILITY__TRACING_ENABLED`` is true. Both functions are idempotent.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI

from app.core.config import Settings

logger = logging.getLogger(__name__)

_TRACING_CONFIGURED = False


def _tracing_active(settings: Settings) -> bool:
    obs = settings.observability
    return obs.tracing_enabled and bool(obs.otlp_endpoint)


def configure_tracing(settings: Settings, *, service_name: str) -> bool:
    """Configure the global tracer provider + OTLP exporter for this process.

    Returns ``True`` if tracing is active, ``False`` if disabled/unconfigured.
    Idempotent: repeated calls are no-ops after the first success.
    """
    global _TRACING_CONFIGURED
    if not _tracing_active(settings):
        return False
    if _TRACING_CONFIGURED:
        return True

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

    obs = settings.observability
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(
        resource=resource,
        sampler=ParentBased(TraceIdRatioBased(obs.trace_sample_ratio)),
    )
    # OTLP/HTTP exporter wants the full signal URL; the setting is the base endpoint.
    exporter = OTLPSpanExporter(endpoint=f"{obs.otlp_endpoint.rstrip('/')}/v1/traces")
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    HTTPXClientInstrumentor().instrument()
    SQLAlchemyInstrumentor().instrument()

    _TRACING_CONFIGURED = True
    logger.info("OpenTelemetry tracing enabled for %s -> %s", service_name, obs.otlp_endpoint)
    return True


def instrument_fastapi(app: FastAPI, settings: Settings) -> None:
    """Instrument the FastAPI app for server spans, if tracing is active."""
    if not _tracing_active(settings):
        return
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app)
