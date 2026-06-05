"""Async Redis client built from settings.

A single ``ConnectionPool`` is created per process and shared across requests.
The ``get_redis`` dependency yields a client backed by the shared pool so that
closing the client does not drain the pool.

Usage::

    from app.core.redis import get_redis
    # In a FastAPI endpoint:
    redis = Depends(get_redis)
"""
from __future__ import annotations

import redis.asyncio as aioredis
from fastapi import Depends
from redis.asyncio import Redis

from app.core.config import RedisSettings, Settings, get_settings

_pool: aioredis.ConnectionPool | None = None


def _build_pool(redis_cfg: RedisSettings) -> aioredis.ConnectionPool:
    return aioredis.ConnectionPool(
        host=redis_cfg.host,
        port=redis_cfg.port,
        db=redis_cfg.db,
        decode_responses=True,
    )


def get_pool(settings: Settings) -> aioredis.ConnectionPool:
    """Return (or create) the shared connection pool."""
    global _pool
    if _pool is None:
        _pool = _build_pool(settings.redis)
    return _pool


async def get_redis(
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> Redis:
    """FastAPI dependency: return an async Redis client backed by the shared pool.

    ``redis.asyncio.Redis`` is not subscriptable at runtime in redis-py 8.x,
    so we use the unsubscripted form in all runtime positions.
    """
    pool = get_pool(settings)
    return aioredis.Redis(connection_pool=pool)
