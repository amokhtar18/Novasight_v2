"""Tests for the bootstrap seed script.

Verifies the seed reads its tenant identity from settings (not literals),
provisions the full set of rows (tenant + resource map + admin user), and is
idempotent on re-run.
"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tenant, User
from app.scripts.seed import seed_tenant

_SEED_ENV: dict[str, str] = {
    "ENVIRONMENT": "test",
    "POSTGRES__HOST": "localhost",
    "POSTGRES__USER": "test",
    "POSTGRES__PASSWORD": "test",
    "POSTGRES__DB": "test",
    "REDIS__HOST": "localhost",
    "OBJECT_STORE__ENDPOINT_URL": "http://localhost:9000",
    "OBJECT_STORE__ACCESS_KEY": "test",
    "OBJECT_STORE__SECRET_KEY": "test",
    "OBJECT_STORE__BUCKET": "test",
    "ICEBERG__CATALOG_URI": "http://localhost:8181",
    "ICEBERG__WAREHOUSE": "s3://test/",
    "CLICKHOUSE__HOST": "localhost",
    "CLICKHOUSE__PASSWORD": "test",
    "AI__PROVIDER": "openai",
    "AI__MODEL": "gpt-4o",
    "AI__API_KEY": "test",
    "AI__PROMPT_TEMPLATE_DIR": "prompts",
    "CUBE__BASE_URL": "http://cube:4000",
    "CUBE__API_SECRET": "test-cube-secret-at-least-32-chars!",
    "AUTH__OIDC_ISSUER": "http://localhost/",
    "AUTH__OIDC_AUDIENCE": "novasight",
    "AUTH__JWKS_URL": "http://localhost/.well-known/jwks.json",
    "SEED_TENANT__SLUG": "local",
    "SEED_TENANT__NAME": "Local Tenant",
    "SEED_TENANT__ADMIN_EMAIL": "admin@local.test",
}


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch):
    from app.core.config import get_settings

    for key, value in _SEED_ENV.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    try:
        yield get_settings()
    finally:
        get_settings.cache_clear()


async def test_seed_creates_tenant_from_settings(
    session: AsyncSession, settings
) -> None:
    tenant = await seed_tenant(session, settings)

    assert tenant.slug == settings.seed_tenant.slug == "local"
    assert tenant.name == "Local Tenant"
    # Resources derived from the slug and persisted on the mapping.
    assert tenant.resource_map.iceberg_namespace == "local"
    assert tenant.resource_map.clickhouse_db == "tenant_local"
    assert tenant.resource_map.dbt_schema == "tenant_local"
    # Admin user provisioned from settings.
    assert [u.email for u in tenant.users] == ["admin@local.test"]


async def test_seed_is_idempotent(session: AsyncSession, settings) -> None:
    first = await seed_tenant(session, settings)
    second = await seed_tenant(session, settings)

    assert first.id == second.id
    tenant_count = await session.scalar(select(func.count()).select_from(Tenant))
    user_count = await session.scalar(select(func.count()).select_from(User))
    assert tenant_count == 1
    assert user_count == 1
