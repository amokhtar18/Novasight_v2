"""Seed the bootstrap tenant from settings.

Creates one ``Tenant`` (plus its ``TenantResourceMap`` and an admin ``User``)
using values from :class:`app.core.config.SeedTenantSettings` — never literals.
Physical resource names are derived via :mod:`app.tenancy.resources`, so the
seed produces exactly what the rest of the system expects to resolve.

Idempotent: re-running with the same slug is a no-op.

Run with::

    cd backend
    uv run python -m app.scripts.seed
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import get_engine
from app.models import Tenant, TenantResourceMap, User
from app.tenancy import resources_for_slug

logger = logging.getLogger(__name__)


async def seed_tenant(session: AsyncSession, settings: Settings) -> Tenant:
    """Create the configured bootstrap tenant if it does not already exist.

    Returns the existing or newly created ``Tenant``. The caller owns the
    transaction (commit/rollback).
    """
    seed = settings.seed_tenant

    existing = await session.scalar(select(Tenant).where(Tenant.slug == seed.slug))
    if existing is not None:
        logger.info("tenant %r already exists (id=%s) — skipping", seed.slug, existing.id)
        return existing

    resources = resources_for_slug(seed.slug)
    tenant = Tenant(
        slug=seed.slug,
        name=seed.name,
        status="active",
        resource_map=TenantResourceMap(
            iceberg_namespace=resources.iceberg_namespace,
            clickhouse_db=resources.clickhouse_db,
            dbt_schema=resources.dbt_schema,
        ),
        users=[User(email=seed.admin_email, is_active=True)],
    )
    session.add(tenant)
    await session.flush()
    logger.info(
        "seeded tenant %r (id=%s): namespace=%s clickhouse_db=%s dbt_schema=%s admin=%s",
        tenant.slug,
        tenant.id,
        resources.iceberg_namespace,
        resources.clickhouse_db,
        resources.dbt_schema,
        seed.admin_email,
    )
    return tenant


async def main() -> None:
    settings = get_settings()
    engine = get_engine(settings)
    async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
        await seed_tenant(session, settings)
    await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
