"""Tests for POST /semantic/values — grounded distinct values for filter dropdowns."""
from __future__ import annotations

import time
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.tenancy.context import TenantContext

_SESSION_SECRET = "test-session-secret-do-not-use-in-production-0123456789"
_FAKE_ENV = {
    "ENVIRONMENT": "test", "POSTGRES__HOST": "localhost", "POSTGRES__USER": "test",
    "POSTGRES__PASSWORD": "test", "POSTGRES__DB": "test", "REDIS__HOST": "localhost",
    "OBJECT_STORE__ENDPOINT_URL": "http://localhost:9000", "OBJECT_STORE__ACCESS_KEY": "test",
    "OBJECT_STORE__SECRET_KEY": "test", "OBJECT_STORE__BUCKET": "test",
    "ICEBERG__CATALOG_URI": "http://localhost:8181", "ICEBERG__WAREHOUSE": "s3://test/",
    "CLICKHOUSE__HOST": "localhost", "CLICKHOUSE__PASSWORD": "test",
    "AI__PROVIDER": "openai", "AI__MODEL": "gpt-4o", "AI__API_KEY": "test",
    "AI__PROMPT_TEMPLATE_DIR": "prompts", "CUBE__BASE_URL": "http://cube:4000",
    "CUBE__API_SECRET": "test-cube-secret-at-least-32-chars!",
    "AUTH__SESSION_SECRET": _SESSION_SECRET, "AUTH__TENANT_CLAIM": "tenant",
    "SEED_TENANT__SLUG": "local", "SEED_TENANT__NAME": "Local Tenant",
    "SEED_TENANT__ADMIN_EMAIL": "admin@local.test",
}
_META = {"cubes": [{
    "name": "regional_sales", "title": "Regional Sales",
    "measures": [{"name": "regional_sales.total_amount", "title": "Total", "type": "number"}],
    "dimensions": [{"name": "regional_sales.region", "title": "Region", "type": "string"}],
}]}


class _FakeCube:
    def __init__(self) -> None:
        self.seen_dims: list[list[str]] = []
        self.seen_filters: list[Any] = []
        self.seen_limits: list[int | None] = []
        self.call_count = 0

    async def meta(self, ctx: TenantContext) -> dict[str, Any]:
        return _META

    async def query(self, ctx: TenantContext, *, measures: list[str], dimensions: list[str],
                    order: dict[str, str] | None = None, limit: int | None = None,
                    filters: list[dict[str, Any]] | None = None,
                    time_dimensions: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        self.call_count += 1
        self.seen_dims.append(dimensions)
        self.seen_filters.append(filters)
        self.seen_limits.append(limit)
        return [{"regional_sales.region": "west"}, {"regional_sales.region": "east"},
                {"regional_sales.region": "west"}]  # duplicate proves dedupe


@pytest.fixture(autouse=True)
def _patch_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in _FAKE_ENV.items():
        monkeypatch.setenv(k, v)


@pytest.fixture()
def fake_cube() -> _FakeCube:
    return _FakeCube()


@pytest.fixture()
def client_with_db(session: AsyncSession, fake_cube: _FakeCube) -> TestClient:  # type: ignore[return]
    from app.ai.semantic.client import get_semantic_layer_client
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
    app.dependency_overrides[get_semantic_layer_client] = lambda: fake_cube
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c  # type: ignore[misc]
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def _auth(tenant: str = "local") -> dict[str, str]:
    payload = {"sub": "c", "email": "c@x", "tenant": tenant, "roles": [],
               "typ": "access", "exp": int(time.time()) + 3600}
    return {"Authorization": f"Bearer {jwt.encode(payload, _SESSION_SECRET, algorithm='HS256')}"}


@pytest.mark.asyncio
async def test_values_grounded_dedup_ordered(client_with_db: TestClient, make_tenant: Any,
                                             fake_cube: _FakeCube) -> None:
    await make_tenant("local")
    resp = client_with_db.post("/api/v1/semantic/values", headers=_auth(),
                               json={"member": "regional_sales.region"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["values"] == ["west", "east"]  # deduped, first-seen order
    assert fake_cube.seen_dims[-1] == ["regional_sales.region"]


@pytest.mark.asyncio
async def test_values_search_becomes_contains_filter(client_with_db: TestClient, make_tenant: Any,
                                                     fake_cube: _FakeCube) -> None:
    await make_tenant("local")
    resp = client_with_db.post("/api/v1/semantic/values", headers=_auth(),
                               json={"member": "regional_sales.region", "search": "wes"})
    assert resp.status_code == 200, resp.text
    assert {"member": "regional_sales.region", "operator": "contains", "values": ["wes"]} \
        in (fake_cube.seen_filters[-1] or [])


@pytest.mark.asyncio
async def test_values_forwards_parent_constraints(client_with_db: TestClient, make_tenant: Any,
                                                  fake_cube: _FakeCube) -> None:
    await make_tenant("local")
    resp = client_with_db.post("/api/v1/semantic/values", headers=_auth(), json={
        "member": "regional_sales.region",
        "constraints": [{"member": "regional_sales.region", "operator": "equals", "values": ["x"]}],
    })
    assert resp.status_code == 200, resp.text
    assert {"member": "regional_sales.region", "operator": "equals", "values": ["x"]} \
        in (fake_cube.seen_filters[-1] or [])


@pytest.mark.asyncio
async def test_values_rejects_ungoverned_member_without_cube_call(
    client_with_db: TestClient, make_tenant: Any, fake_cube: _FakeCube) -> None:
    await make_tenant("local")
    resp = client_with_db.post("/api/v1/semantic/values", headers=_auth(),
                               json={"member": "regional_sales.secret"})
    assert resp.status_code == 422, resp.text
    assert fake_cube.call_count == 0


@pytest.mark.asyncio
async def test_values_rejects_ungoverned_constraint_member(
    client_with_db: TestClient, make_tenant: Any, fake_cube: _FakeCube) -> None:
    await make_tenant("local")
    resp = client_with_db.post("/api/v1/semantic/values", headers=_auth(), json={
        "member": "regional_sales.region",
        "constraints": [{"member": "regional_sales.secret", "operator": "equals", "values": ["x"]}],
    })
    assert resp.status_code == 422, resp.text
    assert fake_cube.call_count == 0


@pytest.mark.asyncio
async def test_values_clamps_limit_to_cap(client_with_db: TestClient, make_tenant: Any,
                                          fake_cube: _FakeCube) -> None:
    from app.core.config import get_settings
    await make_tenant("local")
    cap = get_settings().max_filter_values
    resp = client_with_db.post("/api/v1/semantic/values", headers=_auth(),
                               json={"member": "regional_sales.region", "limit": 10_000_000})
    assert resp.status_code == 200, resp.text
    assert fake_cube.seen_limits[-1] == cap
