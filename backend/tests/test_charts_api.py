"""Tests for the saved-chart API (#9 — chart persistence).

Charts persist a ``ChartSpec`` to Postgres, scoped to a tenant. Covers create/list/
get/update/delete, spec round-trip integrity, and tenant isolation (a chart owned by
another tenant is indistinguishable from not-found — 404, never a cross-tenant leak).
"""
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


def _spec(title: str = "Total by region") -> dict[str, Any]:
    """A valid semantic-path ChartSpec (metric_refs + dotted encoding fields)."""
    return {
        "version": "1",
        "type": "bar",
        "query": {"metric_refs": ["regional_sales.total_amount"]},
        "encoding": {
            "x": "regional_sales.region",
            "series": [{"field": "regional_sales.total_amount", "name": "Total"}],
        },
        "options": {"title": title},
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


def _auth(tenant: str = "local") -> dict[str, str]:
    payload = {
        "sub": "caller",
        "email": "c@x",
        "tenant": tenant,
        "roles": [],
        "typ": "access",
        "exp": int(time.time()) + 3600,
    }
    return {"Authorization": f"Bearer {jwt.encode(payload, _SESSION_SECRET, algorithm='HS256')}"}


@pytest.mark.asyncio
async def test_create_and_get_round_trip(
    client_with_db: TestClient, make_tenant: Any
) -> None:
    await make_tenant("local")
    resp = client_with_db.post(
        "/api/v1/charts",
        headers=_auth(),
        json={"name": "Sales", "spec": _spec(), "source_kind": "semantic",
              "source_ref": "regional_sales"},
    )
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert created["name"] == "Sales"
    assert created["source_kind"] == "semantic"
    assert created["source_ref"] == "regional_sales"
    assert created["owner_id"] is None
    # Spec round-trips exactly (the renderer contract is preserved).
    assert created["spec"]["encoding"]["x"] == "regional_sales.region"

    got = client_with_db.get(f"/api/v1/charts/{created['id']}", headers=_auth())
    assert got.status_code == 200
    assert got.json()["spec"]["query"]["metric_refs"] == ["regional_sales.total_amount"]


@pytest.mark.asyncio
async def test_create_rejects_invalid_spec(
    client_with_db: TestClient, make_tenant: Any
) -> None:
    await make_tenant("local")
    bad = _spec()
    # A pie/bar chart without encoding.x is invalid per the ChartSpec contract.
    bad["encoding"]["x"] = None
    resp = client_with_db.post(
        "/api/v1/charts", headers=_auth(), json={"name": "bad", "spec": bad}
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_and_delete(client_with_db: TestClient, make_tenant: Any) -> None:
    await make_tenant("local")
    cid = client_with_db.post(
        "/api/v1/charts", headers=_auth(), json={"name": "v1", "spec": _spec()}
    ).json()["id"]

    upd = client_with_db.patch(
        f"/api/v1/charts/{cid}", headers=_auth(), json={"name": "v2"}
    )
    assert upd.status_code == 200
    assert upd.json()["name"] == "v2"

    assert client_with_db.delete(f"/api/v1/charts/{cid}", headers=_auth()).status_code == 204
    assert client_with_db.get(f"/api/v1/charts/{cid}", headers=_auth()).status_code == 404


@pytest.mark.asyncio
async def test_list_and_tenant_isolation(
    client_with_db: TestClient, make_tenant: Any
) -> None:
    await make_tenant("local")
    await make_tenant("other")
    cid = client_with_db.post(
        "/api/v1/charts", headers=_auth("local"), json={"name": "local chart", "spec": _spec()}
    ).json()["id"]

    # local sees exactly its own chart.
    local_list = client_with_db.get("/api/v1/charts", headers=_auth("local")).json()
    assert len(local_list) == 1

    # other sees nothing and cannot get/delete local's chart (404, not 403/200).
    assert client_with_db.get("/api/v1/charts", headers=_auth("other")).json() == []
    assert client_with_db.get(f"/api/v1/charts/{cid}", headers=_auth("other")).status_code == 404
    assert (
        client_with_db.delete(f"/api/v1/charts/{cid}", headers=_auth("other")).status_code == 404
    )
    # local's chart is untouched.
    assert client_with_db.get(f"/api/v1/charts/{cid}", headers=_auth("local")).status_code == 200
