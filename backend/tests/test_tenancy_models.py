"""Tenant-isolation tests for the control-plane models.

The acceptance criterion for Task 0.4 is that fixtures can create tenants A and
B; these tests use that to prove the isolation invariant at the data-model
level: A and B get distinct identities and distinct physical resources, and a
tenant-scoped query never returns the other tenant's rows.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.tenancy import resources_for_slug


async def test_create_tenants_a_and_b(make_tenant) -> None:
    """Both tenants are created with distinct ids and resource mappings."""
    a = await make_tenant("acme", admin_email="admin@acme.test")
    b = await make_tenant("globex", admin_email="admin@globex.test")

    assert a.id != b.id
    # Derived names match the convention and never collide.
    assert a.resource_map.iceberg_namespace == "acme"
    assert a.resource_map.clickhouse_db == "tenant_acme"
    assert a.resource_map.dbt_schema == "tenant_acme"
    assert b.resource_map.clickhouse_db == "tenant_globex"
    assert a.resource_map.clickhouse_db != b.resource_map.clickhouse_db


async def test_user_query_is_tenant_scoped(make_tenant, session: AsyncSession) -> None:
    """Filtering users by tenant_id returns only that tenant's users."""
    a = await make_tenant("acme", admin_email="admin@acme.test")
    b = await make_tenant("globex", admin_email="admin@globex.test")

    a_users = (await session.scalars(select(User).where(User.tenant_id == a.id))).all()
    b_users = (await session.scalars(select(User).where(User.tenant_id == b.id))).all()

    assert {u.email for u in a_users} == {"admin@acme.test"}
    assert {u.email for u in b_users} == {"admin@globex.test"}
    # No row leaks across the boundary.
    assert a.id not in {u.tenant_id for u in b_users}


async def test_duplicate_slug_rejected(make_tenant, session: AsyncSession) -> None:
    """Slugs are globally unique — two tenants cannot share one."""
    await make_tenant("acme")
    with pytest.raises(IntegrityError):
        await make_tenant("acme")
    await session.rollback()


async def test_same_email_allowed_across_tenants_not_within(
    make_tenant, session: AsyncSession
) -> None:
    """Email is unique per tenant: reusable across tenants, not within one."""
    a = await make_tenant("acme", admin_email="shared@example.test")
    await make_tenant("globex", admin_email="shared@example.test")  # different tenant: OK

    # Same email within tenant A: rejected by the composite unique constraint.
    session.add(User(tenant_id=a.id, email="shared@example.test"))
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


def test_resources_for_slug_rejects_unsafe_slug() -> None:
    """The derivation refuses slugs that aren't safe identifier fragments."""
    with pytest.raises(ValueError, match="invalid tenant slug"):
        resources_for_slug("Bad Slug!")
