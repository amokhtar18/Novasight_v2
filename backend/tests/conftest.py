"""Shared test fixtures for control-plane models.

Provides an in-memory async SQLite database (no live infra needed) plus a
``make_tenant`` factory so tenant-isolation tests can spin up tenants A and B
quickly. SQLite stands in for Postgres here: the models use portable types
(``Uuid``, ``func.now()``) so the same schema builds on both.
"""
from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator

import jwt
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import Base, Tenant, TenantResourceMap, User
from app.tenancy import resources_for_slug

# --- Shared API-test scaffolding ---------------------------------------------
# The canonical fake environment, the session signing secret, and an auth-header
# helper, so the (identical) per-file copies of this boilerplate stop drifting.
# Settings load entirely from the environment (golden rule #1), so every API test
# patches FAKE_ENV in before the app builds; auth_headers signs the HS256 access
# token the password-mode backend verifies. Importable via ``from tests.conftest
# import FAKE_ENV, auth_headers`` (same pattern as MakeTenant).

# Signs the HS256 access tokens core/security verifies in password mode.
SESSION_SECRET = "test-session-secret-do-not-use-in-production-0123456789"

FAKE_ENV: dict[str, str] = {
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
    "AUTH__SESSION_SECRET": SESSION_SECRET,
    "AUTH__TENANT_CLAIM": "tenant",
    "SEED_TENANT__SLUG": "local",
    "SEED_TENANT__NAME": "Local Tenant",
    "SEED_TENANT__ADMIN_EMAIL": "admin@local.test",
}


def auth_headers(tenant: str = "local", roles: list[str] | None = None) -> dict[str, str]:
    """A Bearer header carrying a session-signed access token for ``tenant``/``roles``."""
    payload = {
        "sub": "caller",
        "email": "c@x",
        "tenant": tenant,
        "roles": roles or [],
        "typ": "access",
        "exp": int(time.time()) + 3600,
    }
    return {"Authorization": f"Bearer {jwt.encode(payload, SESSION_SECRET, algorithm='HS256')}"}


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


@pytest.fixture
def client_with_db(session: AsyncSession) -> Iterator[TestClient]:
    """A ``TestClient`` with ``get_db`` + ``get_tenant_registry`` bound to the test session.

    Covers the common API-test case. Env is patched by the requesting module's autouse
    ``_patch_env`` (which runs first), so settings load against FAKE_ENV here. Files that
    need extra ``dependency_overrides`` define their own ``client_with_db`` (which shadows
    this one for that module).
    """
    from app.core.config import get_settings
    from app.core.db import get_db
    from app.main import app
    from app.tenancy.registry import TenantRegistry, get_tenant_registry

    get_settings.cache_clear()

    async def _fake_db() -> AsyncIterator[AsyncSession]:
        yield session

    async def _fake_registry() -> TenantRegistry:
        return TenantRegistry(session)

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_tenant_registry] = _fake_registry

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c

    app.dependency_overrides.clear()
    get_settings.cache_clear()
