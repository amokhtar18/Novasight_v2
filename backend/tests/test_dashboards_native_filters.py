"""Native-filter persistence + the removal of the 'filter' tile kind (Slice C)."""
from __future__ import annotations

import time
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

_SESSION_SECRET = "test-session-secret-do-not-use-in-production-0123456789"

_FAKE_ENV: dict[str, str] = {
    "ENVIRONMENT": "test",
    "POSTGRES__HOST": "localhost", "POSTGRES__USER": "test",
    "POSTGRES__PASSWORD": "test", "POSTGRES__DB": "test",
    "REDIS__HOST": "localhost",
    "OBJECT_STORE__ENDPOINT_URL": "http://localhost:9000",
    "OBJECT_STORE__ACCESS_KEY": "test", "OBJECT_STORE__SECRET_KEY": "test",
    "OBJECT_STORE__BUCKET": "test",
    "ICEBERG__CATALOG_URI": "http://localhost:8181", "ICEBERG__WAREHOUSE": "s3://test/",
    "CLICKHOUSE__HOST": "localhost", "CLICKHOUSE__PASSWORD": "test",
    "AI__PROVIDER": "openai", "AI__MODEL": "gpt-4o", "AI__API_KEY": "test",
    "AI__PROMPT_TEMPLATE_DIR": "prompts",
    "CUBE__BASE_URL": "http://cube:4000",
    "CUBE__API_SECRET": "test-cube-secret-at-least-32-chars!",
    "AUTH__SESSION_SECRET": _SESSION_SECRET, "AUTH__TENANT_CLAIM": "tenant",
    "SEED_TENANT__SLUG": "local", "SEED_TENANT__NAME": "Local Tenant",
    "SEED_TENANT__ADMIN_EMAIL": "admin@local.test",
}


@pytest.fixture(autouse=True)
def _patch_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in _FAKE_ENV.items():
        monkeypatch.setenv(k, v)


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


def _auth(tenant: str = "local") -> dict[str, str]:
    payload = {"sub": "caller", "email": "c@x", "tenant": tenant, "roles": [],
               "typ": "access", "exp": int(time.time()) + 3600}
    return {"Authorization": f"Bearer {jwt.encode(payload, _SESSION_SECRET, algorithm='HS256')}"}


@pytest.mark.asyncio
async def test_dashboard_round_trips_native_filters(client_with_db: TestClient, make_tenant: Any) -> None:
    await make_tenant("local")
    created = client_with_db.post("/api/v1/dashboards", headers=_auth(), json={"name": "D"})
    assert created.status_code == 201, created.text
    did = created.json()["id"]

    nf = {
        "id": "f1", "kind": "value", "member": "regional_sales.region",
        "operator": "equals", "default_values": ["west"],
        "scope": {"mode": "auto", "tile_ids": []},
    }
    patched = client_with_db.patch(
        f"/api/v1/dashboards/{did}", headers=_auth(), json={"native_filters": [nf]}
    )
    assert patched.status_code == 200, patched.text
    got = client_with_db.get(f"/api/v1/dashboards/{did}", headers=_auth())
    assert got.json()["native_filters"][0]["member"] == "regional_sales.region"
    assert got.json()["native_filters"][0]["default_values"] == ["west"]


@pytest.mark.asyncio
async def test_filter_tile_kind_is_rejected(client_with_db: TestClient, make_tenant: Any) -> None:
    await make_tenant("local")
    did = client_with_db.post("/api/v1/dashboards", headers=_auth(), json={"name": "D"}).json()["id"]
    resp = client_with_db.post(
        f"/api/v1/dashboards/{did}/tiles", headers=_auth(),
        json={"kind": "filter", "content": {"member": "regional_sales.region"}},
    )
    assert resp.status_code == 422, resp.text
