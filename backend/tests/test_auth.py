"""Tests for auth + tenant context (Task 0.5).

All tests run in dev-stub (HS256) mode — no JWKS network calls needed.
Tokens are signed in-process with the configured ``dev_stub_secret``.

Coverage:
  (a) Valid token + known tenant → 200 with correct TenantContext.
  (b) No token → 401.
  (c) Invalid/expired token → 401.
  (d) Token for unknown tenant → 403 (fail closed).
  (e) Token for suspended tenant → 403 (fail closed).
  (f) client-supplied ``tenant_id`` in the POST body is ignored; the response
      reflects the TOKEN's tenant, never the body's value.
  (g) Tenant A's token cannot resolve Tenant B's context.
"""
from __future__ import annotations

import time
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tenant
from app.tenancy import resources_for_slug

# ---------------------------------------------------------------------------
# Fake environment — extends the health-test baseline with AUTH__ dev-stub vars.
# ---------------------------------------------------------------------------

_DEV_STUB_SECRET = "test-dev-stub-secret-do-not-use-in-production"  # noqa: S105

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
    # Auth — dev-stub HS256 mode
    "AUTH__OIDC_ISSUER": "",
    "AUTH__OIDC_AUDIENCE": "",
    "AUTH__JWKS_URL": "",
    "AUTH__DEV_STUB": "true",
    "AUTH__DEV_STUB_SECRET": _DEV_STUB_SECRET,
    "AUTH__TENANT_CLAIM": "tenant",
    "SEED_TENANT__SLUG": "local",
    "SEED_TENANT__NAME": "Local Tenant",
    "SEED_TENANT__ADMIN_EMAIL": "admin@local.test",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token(
    tenant_slug: str,
    *,
    secret: str = _DEV_STUB_SECRET,
    subject: str = "user-sub-123",
    email: str = "user@example.com",
    exp_offset: int = 3600,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Sign an HS256 JWT with the dev-stub secret."""
    payload: dict[str, Any] = {
        "sub": subject,
        "email": email,
        "tenant": tenant_slug,
        "exp": int(time.time()) + exp_offset,
        "iat": int(time.time()),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, secret, algorithm="HS256")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _FAKE_ENV.items():
        monkeypatch.setenv(key, value)


@pytest.fixture()
def client_with_db(session: AsyncSession) -> TestClient:  # type: ignore[return]
    """Build a TestClient with settings overrides and the in-memory DB session."""
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


# ---------------------------------------------------------------------------
# (a) Valid token + known active tenant → 200 with correct context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_me_valid_token(
    client_with_db: TestClient,
    make_tenant: Any,
) -> None:
    """A valid token resolves to the correct TenantContext; all fields come from DB."""
    tenant: Tenant = await make_tenant("acmecorp", name="Acme Corp")
    token = _make_token("acmecorp")

    response = client_with_db.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tenant_id"] == str(tenant.id)

    resources = resources_for_slug("acmecorp")
    assert body["iceberg_namespace"] == resources.iceberg_namespace
    assert body["clickhouse_db"] == resources.clickhouse_db
    assert body["dbt_schema"] == resources.dbt_schema


# ---------------------------------------------------------------------------
# (b) No token → 401
# ---------------------------------------------------------------------------


def test_get_me_no_token(client_with_db: TestClient) -> None:
    """Requests without a token are rejected with 401."""
    response = client_with_db.get("/api/v1/me")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# (c) Invalid token → 401; expired token → 401
# ---------------------------------------------------------------------------


def test_get_me_invalid_token(client_with_db: TestClient) -> None:
    """A syntactically invalid token is rejected with 401."""
    response = client_with_db.get(
        "/api/v1/me",
        headers={"Authorization": "Bearer not.a.valid.jwt"},
    )
    assert response.status_code == 401


def test_get_me_expired_token(client_with_db: TestClient) -> None:
    """An expired token is rejected with 401."""
    token = _make_token("acmecorp", exp_offset=-1)
    response = client_with_db.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401


def test_get_me_wrong_secret(client_with_db: TestClient) -> None:
    """A token signed with a different secret is rejected with 401."""
    wrong_secret = "wrong-secret-value-that-does-not-match"  # noqa: S105
    token = _make_token("acmecorp", secret=wrong_secret)
    response = client_with_db.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# (d) Token for unknown tenant → 403 (fail closed)
# ---------------------------------------------------------------------------


def test_get_me_unknown_tenant(client_with_db: TestClient) -> None:
    """A token for a tenant that does not exist in the registry fails closed (403)."""
    token = _make_token("nonexistent_tenant")
    response = client_with_db.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# (e) Suspended tenant → 403 (fail closed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_me_suspended_tenant(
    client_with_db: TestClient,
    session: AsyncSession,
    make_tenant: Any,
) -> None:
    """A token for a suspended tenant fails closed (403)."""
    tenant: Tenant = await make_tenant("suspended_co")
    tenant.status = "suspended"
    session.add(tenant)
    await session.flush()

    token = _make_token("suspended_co")
    response = client_with_db.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# (f) POST /me — body tenant_id is ignored; response uses TOKEN's tenant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_me_body_tenant_id_is_ignored(
    client_with_db: TestClient,
    make_tenant: Any,
) -> None:
    """The client-supplied tenant_id in the POST body is silently discarded.

    The response must reflect the TOKEN's tenant, never the body's value.
    """
    tenant_a: Tenant = await make_tenant("tenant_alpha")
    tenant_b: Tenant = await make_tenant("tenant_beta")

    # Token is for tenant_alpha; body claims tenant_beta's id.
    token = _make_token("tenant_alpha")
    response = client_with_db.post(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"tenant_id": str(tenant_b.id)},  # client lies
    )

    assert response.status_code == 200, response.text
    body = response.json()
    # Must resolve to tenant_alpha, not tenant_beta
    assert body["tenant_id"] == str(tenant_a.id)
    assert body["tenant_id"] != str(tenant_b.id)

    resources_a = resources_for_slug("tenant_alpha")
    assert body["iceberg_namespace"] == resources_a.iceberg_namespace
    assert body["clickhouse_db"] == resources_a.clickhouse_db
    assert body["dbt_schema"] == resources_a.dbt_schema


# ---------------------------------------------------------------------------
# (g) Tenant A's token cannot resolve Tenant B's context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tenant_isolation(
    client_with_db: TestClient,
    make_tenant: Any,
) -> None:
    """Tenant A's token only resolves Tenant A's resources, not Tenant B's."""
    tenant_a: Tenant = await make_tenant("isolation_a")
    tenant_b: Tenant = await make_tenant("isolation_b")

    # Token for A
    token_a = _make_token("isolation_a")
    resp_a = client_with_db.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp_a.status_code == 200
    body_a = resp_a.json()
    assert body_a["tenant_id"] == str(tenant_a.id)

    # Token for B
    token_b = _make_token("isolation_b")
    resp_b = client_with_db.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp_b.status_code == 200
    body_b = resp_b.json()
    assert body_b["tenant_id"] == str(tenant_b.id)

    # The two resolved contexts must not overlap
    assert body_a["tenant_id"] != body_b["tenant_id"]
    assert body_a["clickhouse_db"] != body_b["clickhouse_db"]
    assert body_a["iceberg_namespace"] != body_b["iceberg_namespace"]
    assert body_a["dbt_schema"] != body_b["dbt_schema"]
