"""Alembic environment — async, settings-driven.

The database URL comes from ``app.core.config`` (never hardcoded). Tests may
override it by setting ``sqlalchemy.url`` on the Alembic ``Config`` before
invoking a command; if unset, it is derived from ``get_settings().postgres.url``.

``target_metadata`` is the control-plane ``Base.metadata`` with every model
imported, so ``--autogenerate`` and ``upgrade`` see the full schema.
"""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Importing the package registers all models on Base.metadata.
from app.core.config import get_settings
from app.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    """URL injected on the Config (tests) wins; otherwise read from settings."""
    injected = config.get_main_option("sqlalchemy.url")
    if injected:
        return injected
    return get_settings().postgres.url


def run_migrations_offline() -> None:
    """Emit SQL without a DB connection (``alembic upgrade --sql``)."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations against a live (async) connection."""
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _database_url()
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
