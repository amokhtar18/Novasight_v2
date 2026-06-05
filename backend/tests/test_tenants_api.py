"""Control-plane tenant endpoint tests (Task 6.3).

Covers the HTTP surface of provisioning: the platform-admin authz gate, status-code
mapping, that resource names are DERIVED (never taken from the client), and that
de-provision removes the tenant. Uses dev-stub (HS256) auth, the in-memory SQLite
session, and fakes for ClickHouse + Iceberg via a ``get_tenant_provisioner`` override.
"""
from __future__ import annotations

import time
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clickhouse import QueryResult

_DEV_STUB_SECRET = "test-dev-stub-secret-do-not-use-in-production"

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


def _make_token(*, roles: list[str] | None = None) -> str:
    payload: dict[str, Any] = {
        "sub": "user-sub-123",
        "email": "user@example.com",
        "tenant": "local",  # required claim; control-plane routes ignore it
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
    }
    if roles is not None:
        payload["roles"] = roles
    return jwt.encode(payload, _DEV_STUB_SECRET, algorithm="HS256")


class _FakeClickHouse:
    def __init__(self) -> None:
        self.databases: set[str] = set()

    @staticmethod
    def _name(sql: str) -> str:
        return sql.split("`")[1]

    def command(self, sql: str, *, database: str | None = None) -> None:
        upper = sql.upper()
        if upper.startswith("CREATE DATABASE"):
            self.databases.add(self._name(sql))
        elif "DROP DATABASE" in upper:
            self.databases.discard(self._name(sql))

    def query(
        self, sql: str, *, database: str, parameters: Any = None, read_only: bool = True
    ) -> QueryResult:
        name = (parameters or {}).get("db")
        return QueryResult(column_names=["1"], rows=[(1,)] if name in self.databases else [])


class _FakeIceberg:
    def __init__(self) -> None:
        self.namespaces: set[str] = set()

    def create_namespace(self, namespace: str) -> None:
        from pyiceberg.exceptions import NamespaceAlreadyExistsError

        if namespace in self.namespaces:
            raise NamespaceAlreadyExistsError(namespace)
        self.namespaces.add(namespace)

    def drop_namespace(self, namespace: str) -> None:
        self.namespaces.discard(namespace)

    def list_tables(self, namespace: str) -> list[tuple[str, ...]]:
        return []

    def purge_table(self, identifier: tuple[str, ...]) -> None:  # pragma: no cover
        pass


@pytest.fixture(autouse=True)
def _patch_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _FAKE_ENV.items():
        monkeypatch.setenv(key, value)


@pytest.fixture()
def client_with_db(session: AsyncSession) -> TestClient:  # type: ignore[return]
    from app.core.config import get_settings
    from app.core.db import get_db
    from app.main import app
    from app.tenancy.provisioning import TenantProvisioner, get_tenant_provisioner

    get_settings.cache_clear()
    ch, ice = _FakeClickHouse(), _FakeIceberg()

    async def _fake_db() -> Any:
        yield session

    def _fake_provisioner() -> TenantProvisioner:
        return TenantProvisioner(db=session, ch=ch, iceberg=ice)

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_tenant_provisioner] = _fake_provisioner

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c  # type: ignore[misc]

    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_provision_requires_authentication(client_with_db: TestClient) -> None:
    resp = client_with_db.post(
        "/api/v1/tenants",
        json={"slug": "acme", "name": "Acme", "admin_email": "a@acme.test"},
    )
    assert resp.status_code == 401


def test_provision_requires_platform_admin_role(client_with_db: TestClient) -> None:
    token = _make_token(roles=["analyst"])  # not a platform admin
    resp = client_with_db.post(
        "/api/v1/tenants",
        headers={"Authorization": f"Bearer {token}"},
        json={"slug": "acme", "name": "Acme", "admin_email": "a@acme.test"},
    )
    assert resp.status_code == 403


def test_provision_succeeds_for_platform_admin(client_with_db: TestClient) -> None:
    token = _make_token(roles=["platform_admin"])
    resp = client_with_db.post(
        "/api/v1/tenants",
        headers={"Authorization": f"Bearer {token}"},
        json={"slug": "acme", "name": "Acme", "admin_email": "a@acme.test"},
    )
    assert resp.status_code == 201
    body = resp.json()
    # Resource names are DERIVED from the slug, never the client.
    assert body["slug"] == "acme"
    assert body["iceberg_namespace"] == "acme"
    assert body["clickhouse_db"] == "tenant_acme"
    assert body["dbt_schema"] == "tenant_acme"
    assert body["status"] == "active"


def test_provision_duplicate_returns_409(client_with_db: TestClient) -> None:
    token = _make_token(roles=["platform_admin"])
    headers = {"Authorization": f"Bearer {token}"}
    body = {"slug": "acme", "name": "Acme", "admin_email": "a@acme.test"}
    assert client_with_db.post("/api/v1/tenants", headers=headers, json=body).status_code == 201
    assert client_with_db.post("/api/v1/tenants", headers=headers, json=body).status_code == 409


def test_provision_invalid_slug_returns_422(client_with_db: TestClient) -> None:
    token = _make_token(roles=["platform_admin"])
    resp = client_with_db.post(
        "/api/v1/tenants",
        headers={"Authorization": f"Bearer {token}"},
        json={"slug": "Bad-Slug", "name": "x", "admin_email": "a@b.test"},
    )
    assert resp.status_code == 422


def test_deprovision_lifecycle(client_with_db: TestClient) -> None:
    token = _make_token(roles=["platform_admin"])
    headers = {"Authorization": f"Bearer {token}"}
    client_with_db.post(
        "/api/v1/tenants",
        headers=headers,
        json={"slug": "acme", "name": "Acme", "admin_email": "a@acme.test"},
    )
    assert client_with_db.delete("/api/v1/tenants/acme", headers=headers).status_code == 204
    # Second delete: already gone -> 404.
    assert client_with_db.delete("/api/v1/tenants/acme", headers=headers).status_code == 404


def test_deprovision_requires_platform_admin(client_with_db: TestClient) -> None:
    token = _make_token(roles=["analyst"])
    resp = client_with_db.delete(
        "/api/v1/tenants/acme", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403
