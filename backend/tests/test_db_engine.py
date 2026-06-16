"""Tests for async engine pool selection (``app.core.db``).

Regression guard for worker pipeline runs getting stuck at ``queued``: the worker runs
each Dramatiq actor in its own ``asyncio.run`` (a fresh event loop), and asyncpg
connections are loop-bound. With a pooled engine, the next job's loop reuses a dead
connection and the actor raises at the first DB call — before the executor can advance
the run row — so the message dead-letters and the row stays ``queued``. The worker thus
disables pooling via ``use_null_pool``; the API keeps the default pool.
"""
from __future__ import annotations

import asyncio
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.pool import NullPool

from app.core import db as db_mod


def _fake_settings() -> Any:
    # get_engine only reads settings.postgres.url; no connection is opened.
    return SimpleNamespace(
        postgres=SimpleNamespace(url="postgresql+asyncpg://u:p@h:5432/d")
    )


@pytest.fixture()
def _reset_engine() -> Iterator[None]:
    """Reset the module engine + pool flag around each test (both are process globals)."""
    db_mod._engine = None
    db_mod._null_pool = False
    yield
    if db_mod._engine is not None:
        asyncio.run(db_mod._engine.dispose())
    db_mod._engine = None
    db_mod._null_pool = False


def test_default_engine_is_pooled(_reset_engine: None) -> None:
    engine = db_mod.get_engine(_fake_settings())
    # The API path keeps connection pooling (long-lived single loop per process).
    assert not isinstance(engine.pool, NullPool)


def test_use_null_pool_disables_pooling(_reset_engine: None) -> None:
    db_mod.use_null_pool()
    engine = db_mod.get_engine(_fake_settings())
    # Worker path: a fresh connection per checkout, never reused across event loops.
    assert isinstance(engine.pool, NullPool)


def test_use_null_pool_must_precede_engine_creation(_reset_engine: None) -> None:
    # Documents the ordering contract: flipping the flag after the engine exists is a
    # no-op (the worker entrypoint calls use_null_pool before the first session).
    first = db_mod.get_engine(_fake_settings())
    db_mod.use_null_pool()
    assert db_mod.get_engine(_fake_settings()) is first
    assert not isinstance(first.pool, NullPool)
