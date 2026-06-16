"""Async SQLAlchemy engine and session factory.

The engine is created lazily from settings so that the module can be imported
without live infrastructure.  Session lifecycle is managed per-request via the
``get_db`` FastAPI dependency.

Usage::

    from app.core.db import get_db
    # In a FastAPI endpoint:
    db: AsyncSession = Depends(get_db)
"""
from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings

# Module-level singletons; initialised on first call to get_engine().
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
# Whether the engine should disable connection pooling. Set once, before the engine
# is created, by ``use_null_pool()`` (the worker entrypoint). See that function.
_null_pool = False


def use_null_pool() -> None:
    """Disable connection pooling for the engine created in this process.

    The worker bridges Dramatiq's sync model to async by wrapping each job in its own
    ``asyncio.run`` — a fresh event loop per job. asyncpg connections are bound to the
    loop that opened them, so a *pooled* connection reused by the next job's loop fails
    at checkout (and leaks the orphaned connection). ``NullPool`` opens and closes a
    connection per checkout, always on the current loop, sidestepping cross-loop reuse.

    Must be called before the first ``get_engine`` (the worker entrypoint does so before
    importing any actor). The API process never calls this and keeps the default pool —
    it serves all requests on one long-lived event loop, where pooling is correct.
    """
    global _null_pool
    _null_pool = True


def get_engine(settings: Settings) -> AsyncEngine:
    """Return (or create) the shared async engine."""
    global _engine
    if _engine is None:
        if _null_pool:
            # NullPool opens a fresh connection per checkout; pool_pre_ping is moot.
            _engine = create_async_engine(settings.postgres.url, echo=False, poolclass=NullPool)
        else:
            _engine = create_async_engine(settings.postgres.url, echo=False, pool_pre_ping=True)
    return _engine


def _get_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(settings),
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


async def get_db(
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yield an ``AsyncSession``, commit on success, rollback on error."""
    factory = _get_session_factory(settings)
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def session_scope(
    settings: Settings | None = None,
) -> AsyncIterator[AsyncSession]:
    """Yield an ``AsyncSession`` for code outside the request cycle (e.g. workers).

    Mirrors ``get_db``'s commit-on-success / rollback-on-error contract but is a
    plain async context manager rather than a FastAPI dependency, so background
    jobs (the reporting worker) can open a session without a request. Settings are
    read from the environment unless injected (tests).
    """
    factory = _get_session_factory(settings or get_settings())
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
