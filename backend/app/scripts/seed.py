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
from app.core.passwords import hash_password
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
    # When an admin password is configured (HS256/password mode), the seeded admin
    # gets a usable login plus the platform-admin and tenant-superuser roles so the
    # install is fully operable out of the box. Without it (OIDC mode), the admin
    # user exists but has no local password — credentials live with the IdP.
    if seed.admin_password is not None:
        admin = User(
            email=seed.admin_email,
            name="Administrator",
            password_hash=hash_password(seed.admin_password.get_secret_value()),
            roles=[settings.auth.platform_admin_role, settings.auth.tenant_superuser_role],
            is_active=True,
        )
    else:
        admin = User(email=seed.admin_email, is_active=True)
    tenant = Tenant(
        slug=seed.slug,
        name=seed.name,
        status="active",
        resource_map=TenantResourceMap(
            iceberg_namespace=resources.iceberg_namespace,
            clickhouse_db=resources.clickhouse_db,
            dbt_schema=resources.dbt_schema,
        ),
        users=[admin],
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
