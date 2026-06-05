"""Health-check endpoint.

``GET /api/v1/health`` probes Postgres (``SELECT 1``) and Redis (``PING``).
Returns 200 when all components are healthy, 503 when any dependency is down.
Routers stay thin: probe logic lives inline here because it is purely I/O and
has no reusable domain meaning — it does not belong in a service.
"""
from __future__ import annotations

import logging
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.redis import get_redis
from app.schemas.health import ComponentStatus, HealthRead

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])

# Annotated aliases keep parameter declarations DRY and satisfy ruff B008.
# aioredis.Redis is not subscriptable at runtime in redis-py 8.x, so we use
# the unsubscripted form here and silence the mypy type-arg complaint.
DbDep = Annotated[AsyncSession, Depends(get_db)]
RedisDep = Annotated[aioredis.Redis, Depends(get_redis)]


async def _probe_postgres(db: AsyncSession) -> ComponentStatus:
    try:
        await db.execute(text("SELECT 1"))
        return ComponentStatus(name="postgres", status="up")
    except Exception as exc:
        logger.error("Postgres health probe failed", extra={"error": str(exc)})
        return ComponentStatus(name="postgres", status="down", detail="unreachable")


async def _probe_redis(redis_client: aioredis.Redis) -> ComponentStatus:
    try:
        await redis_client.ping()
        return ComponentStatus(name="redis", status="up")
    except Exception as exc:
        logger.error("Redis health probe failed", extra={"error": str(exc)})
        return ComponentStatus(name="redis", status="down", detail="unreachable")


@router.get(
    "",
    response_model=HealthRead,
    summary="Liveness / readiness probe",
    responses={
        status.HTTP_200_OK: {"description": "All components healthy"},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "One or more components degraded"},
    },
)
async def health_check(
    db: DbDep,
    redis_client: RedisDep,
) -> JSONResponse:
    """Probe Postgres and Redis; return per-component status.

    HTTP 200 = all up.  HTTP 503 = at least one component down.
    Error details are logged server-side; the response body only reports status.
    """
    components = [
        await _probe_postgres(db),
        await _probe_redis(redis_client),
    ]
    all_up = all(c.status == "up" for c in components)
    body = HealthRead(
        status="healthy" if all_up else "degraded",
        components=components,
    )
    http_status = status.HTTP_200_OK if all_up else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(content=body.model_dump(), status_code=http_status)
