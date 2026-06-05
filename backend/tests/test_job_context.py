"""Tests for background-job tenant resolution (app/tenancy/job_context.py).

A worker is handed only a tenant slug; it must re-derive the full scope from the
registry and fail closed on anything unusable — the same guarantees as the HTTP
boundary, with a domain error instead of a 403.
"""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tenant
from app.tenancy.job_context import JobTenantError, resolve_tenant_context_for_job
from tests.conftest import MakeTenant


@pytest.mark.asyncio
async def test_resolves_active_tenant_to_full_scope(
    session: AsyncSession, make_tenant: MakeTenant
) -> None:
    tenant = await make_tenant("alpha")

    ctx = await resolve_tenant_context_for_job("alpha", session)

    assert ctx.tenant_id == str(tenant.id)
    assert ctx.iceberg_namespace == "alpha"
    assert ctx.clickhouse_db == "tenant_alpha"
    assert ctx.dbt_schema == "tenant_alpha"


@pytest.mark.asyncio
async def test_unknown_slug_fails_closed(session: AsyncSession) -> None:
    with pytest.raises(JobTenantError, match="not found"):
        await resolve_tenant_context_for_job("ghost", session)


@pytest.mark.asyncio
async def test_suspended_tenant_fails_closed(
    session: AsyncSession, make_tenant: MakeTenant
) -> None:
    tenant = await make_tenant("alpha")
    tenant.status = "suspended"
    await session.flush()

    with pytest.raises(JobTenantError, match="not active"):
        await resolve_tenant_context_for_job("alpha", session)


@pytest.mark.asyncio
async def test_tenant_without_resource_map_fails_closed(session: AsyncSession) -> None:
    # An active tenant with no resource map is a data-integrity hole — fail closed.
    session.add(Tenant(slug="orphan", name="Orphan"))
    await session.flush()

    with pytest.raises(JobTenantError, match="no resource map"):
        await resolve_tenant_context_for_job("orphan", session)
