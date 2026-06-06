"""Tests for password authentication (Phase 0 login).

Runs in first-class **password mode** (``AUTH__SESSION_SECRET`` set, ``dev_stub``
off): the backend mints HS256 tokens and verifies them with the same secret. This
exercises the full login → token → protected-call → refresh loop, plus the
fail-closed behaviour that makes auth failures indistinguishable.
"""
from __future__ import annotations

from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.passwords import hash_password, verify_password
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
    # Auth — password (HS256) mode: no dev-stub, no OIDC.
    "AUTH__OIDC_ISSUER": "",
    "AUTH__OIDC_AUDIENCE": "",
    "AUTH__JWKS_URL": "",
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


async def _make_user(
    session: AsyncSession,
    make_tenant: Any,
    *,
    slug: str = "local",
    email: str = "user@example.com",
    password: str = "s3cret-pass",
    roles: list[str] | None = None,
    is_active: bool = True,
) -> tuple[Tenant, User]:
    tenant: Tenant = await make_tenant(slug)
    user = User(
        tenant_id=tenant.id,
        email=email,
        name="Test User",
        password_hash=hash_password(password),
        roles=roles,
        is_active=is_active,
    )
    session.add(user)
    await session.flush()
    return tenant, user


# ---------------------------------------------------------------------------
# password helper
# ---------------------------------------------------------------------------


def test_password_hash_roundtrip() -> None:
    h = hash_password("correct horse battery staple")
    assert h != "correct horse battery staple"
    assert verify_password("correct horse battery staple", h)
    assert not verify_password("wrong", h)
    assert not verify_password("anything", "")


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_success_and_token_works(
    client_with_db: TestClient, session: AsyncSession, make_tenant: Any
) -> None:
    tenant, _ = await _make_user(session, make_tenant, roles=["superuser"])

    resp = client_with_db.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "s3cret-pass", "tenant": "local"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == "user@example.com"
    assert body["user"]["roles"] == ["superuser"]
    assert body["user"]["tenant"] == "local"

    # The issued access token authenticates a protected call.
    me = client_with_db.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 200, me.text
    me_body = me.json()
    assert me_body["tenant_id"] == str(tenant.id)
    assert me_body["email"] == "user@example.com"
    assert me_body["roles"] == ["superuser"]


@pytest.mark.asyncio
async def test_login_defaults_to_seed_tenant_when_omitted(
    client_with_db: TestClient, session: AsyncSession, make_tenant: Any
) -> None:
    await _make_user(session, make_tenant)
    resp = client_with_db.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "s3cret-pass"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["user"]["tenant"] == "local"


@pytest.mark.asyncio
async def test_login_wrong_password(
    client_with_db: TestClient, session: AsyncSession, make_tenant: Any
) -> None:
    await _make_user(session, make_tenant)
    resp = client_with_db.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "nope", "tenant": "local"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_email(
    client_with_db: TestClient, session: AsyncSession, make_tenant: Any
) -> None:
    await _make_user(session, make_tenant)
    resp = client_with_db.post(
        "/api/v1/auth/login",
        json={"email": "ghost@example.com", "password": "s3cret-pass", "tenant": "local"},
    )
    assert resp.status_code == 401


def test_login_unknown_tenant(client_with_db: TestClient) -> None:
    resp = client_with_db.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "s3cret-pass", "tenant": "ghost"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_inactive_user(
    client_with_db: TestClient, session: AsyncSession, make_tenant: Any
) -> None:
    await _make_user(session, make_tenant, is_active=False)
    resp = client_with_db.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "s3cret-pass", "tenant": "local"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# refresh + logout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_issues_new_access_token(
    client_with_db: TestClient, session: AsyncSession, make_tenant: Any
) -> None:
    await _make_user(session, make_tenant, roles=["superuser"])
    login = client_with_db.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "s3cret-pass", "tenant": "local"},
    ).json()

    resp = client_with_db.post(
        "/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]}
    )
    assert resp.status_code == 200, resp.text
    new_access = resp.json()["access_token"]

    me = client_with_db.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {new_access}"}
    )
    assert me.status_code == 200
    assert me.json()["roles"] == ["superuser"]


@pytest.mark.asyncio
async def test_refresh_rejects_access_token(
    client_with_db: TestClient, session: AsyncSession, make_tenant: Any
) -> None:
    """An access token (typ != refresh) cannot be used to refresh."""
    await _make_user(session, make_tenant)
    login = client_with_db.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "s3cret-pass", "tenant": "local"},
    ).json()

    resp = client_with_db.post(
        "/api/v1/auth/refresh", json={"refresh_token": login["access_token"]}
    )
    assert resp.status_code == 401


def test_logout_is_stateless_204(client_with_db: TestClient) -> None:
    assert client_with_db.post("/api/v1/auth/logout").status_code == 204


# ---------------------------------------------------------------------------
# issued-token shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_issued_token_claims(
    client_with_db: TestClient, session: AsyncSession, make_tenant: Any
) -> None:
    _, user = await _make_user(session, make_tenant, roles=["superuser", "x"])
    login = client_with_db.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "s3cret-pass", "tenant": "local"},
    ).json()
    claims = jwt.decode(login["access_token"], _SESSION_SECRET, algorithms=["HS256"])
    assert claims["sub"] == str(user.id)
    assert claims["tenant"] == "local"
    assert claims["email"] == "user@example.com"
    assert set(claims["roles"]) == {"superuser", "x"}
    assert claims["typ"] == "access"
