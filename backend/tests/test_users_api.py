"""Tests for tenant-scoped user management + tenant list/get (Phase 0).

Runs in password (HS256) mode. Tokens are minted directly with the session secret
and the relevant roles so each test exercises the exact authorization path:

  * user management requires the tenant ``superuser`` role (or platform admin);
  * a non-platform-admin cannot grant the platform-admin role (escalation guard);
  * all user queries are tenant-scoped (cross-tenant access is 404);
  * tenant list/get requires the platform-admin role.
"""
from __future__ import annotations

import time
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.passwords import hash_password
from app.models import Tenant, User

_SESSION_SECRET = "test-session-secret-do-not-use-in-production-0123456789"

_FAKE_ENV: dict[str, str] = {
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
    "AUTH__SESSION_SECRET": _SESSION_SECRET,
    "AUTH__TENANT_CLAIM": "tenant",
    "SEED_TENANT__SLUG": "local",
    "SEED_TENANT__NAME": "Local Tenant",
    "SEED_TENANT__ADMIN_EMAIL": "admin@local.test",
}


@pytest.fixture(autouse=True)
def _patch_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _FAKE_ENV.items():
        monkeypatch.setenv(key, value)


@pytest.fixture()
def client_with_db(session: AsyncSession) -> TestClient:  # type: ignore[return]
    from app.core.config import get_settings
    from app.core.db import get_db
    from app.main import app
    from app.tenancy.registry import TenantRegistry, get_tenant_registry

    get_settings.cache_clear()

    async def _fake_db() -> Any:
        yield session

    async def _fake_registry() -> Any:
        return TenantRegistry(session)

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_tenant_registry] = _fake_registry

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c  # type: ignore[misc]

    app.dependency_overrides.clear()
    get_settings.cache_clear()


def _token(tenant: str = "local", *, roles: list[str] | None = None) -> str:
    payload = {
        "sub": "caller-sub",
        "email": "caller@example.com",
        "tenant": tenant,
        "roles": roles or [],
        "typ": "access",
        "exp": int(time.time()) + 3600,
    }
    return jwt.encode(payload, _SESSION_SECRET, algorithm="HS256")


def _auth(roles: list[str] | None = None, tenant: str = "local") -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(tenant, roles=roles)}"}


async def _add_user(
    session: AsyncSession, tenant: Tenant, *, email: str, roles: list[str] | None = None
) -> User:
    user = User(
        tenant_id=tenant.id,
        email=email,
        password_hash=hash_password("placeholder-pass"),
        roles=roles,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


# ---------------------------------------------------------------------------
# user management
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_users_is_tenant_scoped(
    client_with_db: TestClient, session: AsyncSession, make_tenant: Any
) -> None:
    local: Tenant = await make_tenant("local")
    other: Tenant = await make_tenant("other")
    await _add_user(session, local, email="a@local")
    await _add_user(session, other, email="b@other")

    resp = client_with_db.get("/api/v1/users", headers=_auth(["superuser"]))
    assert resp.status_code == 200, resp.text
    emails = {u["email"] for u in resp.json()}
    assert emails == {"a@local"}


@pytest.mark.asyncio
async def test_create_user_requires_superuser(
    client_with_db: TestClient, make_tenant: Any
) -> None:
    await make_tenant("local")
    resp = client_with_db.post(
        "/api/v1/users",
        headers=_auth([]),  # no superuser role
        json={"email": "new@local", "password": "password123"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_user_then_login(
    client_with_db: TestClient, make_tenant: Any
) -> None:
    await make_tenant("local")
    resp = client_with_db.post(
        "/api/v1/users",
        headers=_auth(["superuser"]),
        json={"email": "new@local", "password": "password123", "name": "New"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["email"] == "new@local"

    login = client_with_db.post(
        "/api/v1/auth/login",
        json={"email": "new@local", "password": "password123", "tenant": "local"},
    )
    assert login.status_code == 200, login.text


@pytest.mark.asyncio
async def test_superuser_cannot_grant_platform_admin(
    client_with_db: TestClient, make_tenant: Any
) -> None:
    await make_tenant("local")
    resp = client_with_db.post(
        "/api/v1/users",
        headers=_auth(["superuser"]),
        json={
            "email": "esc@local",
            "password": "password123",
            "roles": ["platform_admin"],
        },
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_platform_admin_can_grant_platform_admin(
    client_with_db: TestClient, make_tenant: Any
) -> None:
    await make_tenant("local")
    resp = client_with_db.post(
        "/api/v1/users",
        headers=_auth(["platform_admin"]),
        json={
            "email": "admin2@local",
            "password": "password123",
            "roles": ["platform_admin"],
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["roles"] == ["platform_admin"]


@pytest.mark.asyncio
async def test_create_duplicate_email_conflict(
    client_with_db: TestClient, session: AsyncSession, make_tenant: Any
) -> None:
    local: Tenant = await make_tenant("local")
    await _add_user(session, local, email="dup@local")
    resp = client_with_db.post(
        "/api/v1/users",
        headers=_auth(["superuser"]),
        json={"email": "dup@local", "password": "password123"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_update_user(
    client_with_db: TestClient, session: AsyncSession, make_tenant: Any
) -> None:
    local: Tenant = await make_tenant("local")
    user = await _add_user(session, local, email="u@local", roles=[])
    resp = client_with_db.patch(
        f"/api/v1/users/{user.id}",
        headers=_auth(["superuser"]),
        json={"name": "Renamed", "roles": ["superuser"], "is_active": False},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "Renamed"
    assert body["roles"] == ["superuser"]
    assert body["is_active"] is False


@pytest.mark.asyncio
async def test_delete_user(
    client_with_db: TestClient, session: AsyncSession, make_tenant: Any
) -> None:
    local: Tenant = await make_tenant("local")
    user = await _add_user(session, local, email="gone@local")
    assert (
        client_with_db.delete(
            f"/api/v1/users/{user.id}", headers=_auth(["superuser"])
        ).status_code
        == 204
    )
    # Now a follow-up update is 404.
    assert (
        client_with_db.patch(
            f"/api/v1/users/{user.id}", headers=_auth(["superuser"]), json={"name": "x"}
        ).status_code
        == 404
    )


@pytest.mark.asyncio
async def test_cross_tenant_user_is_404(
    client_with_db: TestClient, session: AsyncSession, make_tenant: Any
) -> None:
    await make_tenant("local")
    other: Tenant = await make_tenant("other")
    foreign = await _add_user(session, other, email="foreign@other")
    # A superuser of "local" cannot touch "other"'s user — indistinguishable from
    # not-found.
    resp = client_with_db.patch(
        f"/api/v1/users/{foreign.id}",
        headers=_auth(["superuser"], tenant="local"),
        json={"name": "hijack"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# tenant list/get (platform admin)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tenant_list_and_get_requires_platform_admin(
    client_with_db: TestClient, make_tenant: Any
) -> None:
    await make_tenant("local")
    await make_tenant("other")

    # Non-admin → 403.
    assert client_with_db.get("/api/v1/tenants", headers=_auth([])).status_code == 403

    # Platform admin → list both.
    resp = client_with_db.get("/api/v1/tenants", headers=_auth(["platform_admin"]))
    assert resp.status_code == 200, resp.text
    slugs = {t["slug"] for t in resp.json()}
    assert {"local", "other"} <= slugs

    # Get one.
    one = client_with_db.get("/api/v1/tenants/local", headers=_auth(["platform_admin"]))
    assert one.status_code == 200
    assert one.json()["slug"] == "local"

    # Unknown → 404.
    assert (
        client_with_db.get(
            "/api/v1/tenants/ghost", headers=_auth(["platform_admin"])
        ).status_code
        == 404
    )
