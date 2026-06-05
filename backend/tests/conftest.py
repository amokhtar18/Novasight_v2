"""Shared test fixtures for control-plane models.

Provides an in-memory async SQLite database (no live infra needed) plus a
``make_tenant`` factory so tenant-isolation tests can spin up tenants A and B
quickly. SQLite stands in for Postgres here: the models use portable types
(``Uuid``, ``func.now()``) so the same schema builds on both.
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import Base, Tenant, TenantResourceMap, User
from app.tenancy import resources_for_slug


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[object]:
    """A fresh in-memory SQLite engine with the full schema created."""
    eng = create_async_engine(
        "sqlite+aiosqlite://",
        # A single shared connection so the in-memory schema survives across uses.
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest_asyncio.fixture
async def session(engine: object) -> AsyncIterator[AsyncSession]:
    """An ``AsyncSession`` bound to the test engine."""
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)  # type: ignore[arg-type]
    async with factory() as sess:
        yield sess


# A factory: call it with a slug to insert a fully-provisioned tenant.
MakeTenant = Callable[..., Awaitable[Tenant]]


@pytest.fixture
def make_tenant(session: AsyncSession) -> MakeTenant:
    """Return an async factory that creates a tenant + resource map (+ admin user).

    Resource names are derived the same way production provisioning derives them,
    so isolation tests exercise the real naming path.
    """

    async def _make(slug: str, name: str | None = None, admin_email: str | None = None) -> Tenant:
        resources = resources_for_slug(slug)
        tenant = Tenant(
            slug=slug,
            name=name or slug.title(),
            resource_map=TenantResourceMap(
                iceberg_namespace=resources.iceberg_namespace,
                clickhouse_db=resources.clickhouse_db,
                dbt_schema=resources.dbt_schema,
            ),
        )
        if admin_email is not None:
            tenant.users.append(User(email=admin_email))
        session.add(tenant)
        await session.flush()
        return tenant

    return _make
