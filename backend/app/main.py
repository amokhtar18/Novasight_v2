"""FastAPI application entrypoint.

Creates the ``app`` ASGI object, wires up the lifespan (logging configuration),
and mounts the versioned API router.  Everything infrastructure- or
environment-specific comes from settings; the only literals here are
human-readable metadata strings.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.ai.gateway.gateway import close_llm_client
from app.ai.semantic.client import close_http_client
from app.api.v1 import v1_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.observability import setup_fastapi_observability


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    """Run startup/shutdown hooks around the application's lifetime."""
    settings = get_settings()
    configure_logging(level=settings.log_level)
    yield
    # Shutdown: release shared HTTP connection pools — semantic layer (Cube) and
    # LLM gateway (Anthropic).  Add further engine/pool disposal here as those
    # subsystems land.
    await close_http_client()
    await close_llm_client()


app = FastAPI(
    title="Analytica",
    description="Managed, low-code data analytics & BI platform.",
    version="0.1.0",
    lifespan=lifespan,
    # Disable the default /docs and /redoc in production via settings when auth is wired.
)

app.include_router(v1_router)

# Metrics middleware + /metrics endpoint, and OpenTelemetry tracing (no-op until an
# OTLP endpoint is configured). Wired at import so it is in the ASGI stack at startup.
setup_fastapi_observability(app, service_name="analytica-api")
