"""Tests for the semantic-layer API (#9 — governed structured chart-data path).

A live Cube stack is not available, so the ``SemanticLayerClient`` dependency is
overridden with a fake that returns canned meta + rows. Covers model listing, the
grounded happy path (columns aligned to dimensions + measures, Decimal→float),
fail-closed rejection of ungrounded references, and tenant scoping (the fake records
the ``clickhouse_db`` it was called with, proving two tenants resolve to different
databases).
"""
from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.tenancy.context import TenantContext

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

_META: dict[str, Any] = {
    "cubes": [
        {
            "name": "regional_sales",
            "title": "Regional Sales",
            "measures": [
                {"name": "regional_sales.total_amount", "title": "Total", "type": "number"},
            ],
            "dimensions": [
                {"name": "regional_sales.region", "title": "Region", "type": "string"},
            ],
        }
    ]
}


class _FakeCube:
    """A stand-in for ``SemanticLayerClient`` that records the tenant db it saw."""

    def __init__(self) -> None:
        self.seen_dbs: list[str] = []

    async def meta(self, ctx: TenantContext) -> dict[str, Any]:
        self.seen_dbs.append(ctx.clickhouse_db)
        return _META

    async def query(
        self,
        ctx: TenantContext,
        *,
        measures: list[str],
        dimensions: list[str],
        order: dict[str, str] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        self.seen_dbs.append(ctx.clickhouse_db)
        return [
            {"regional_sales.region": "west", "regional_sales.total_amount": Decimal("100.5")},
            {"regional_sales.region": "east", "regional_sales.total_amount": Decimal("200")},
        ]


@pytest.fixture(autouse=True)
def _patch_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _FAKE_ENV.items():
        monkeypatch.setenv(key, value)


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
async def test_list_models(client_with_db: TestClient, make_tenant: Any) -> None:
    await make_tenant("local")
    resp = client_with_db.get("/api/v1/semantic/models", headers=_auth())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 1
    model = body[0]
    assert model["name"] == "regional_sales"
    assert model["measures"][0]["name"] == "regional_sales.total_amount"
    assert model["dimensions"][0]["name"] == "regional_sales.region"


@pytest.mark.asyncio
async def test_query_grounded_ok(client_with_db: TestClient, make_tenant: Any) -> None:
    await make_tenant("local")
    resp = client_with_db.post(
        "/api/v1/semantic/query",
        headers=_auth(),
        json={
            "measures": ["regional_sales.total_amount"],
            "dimensions": ["regional_sales.region"],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Columns are dimensions then measures (the builder's x then series order).
    assert body["columns"] == ["regional_sales.region", "regional_sales.total_amount"]
    assert body["rows"] == [["west", 100.5], ["east", 200.0]]
    assert body["row_count"] == 2


@pytest.mark.asyncio
async def test_query_rejects_ungrounded_measure(
    client_with_db: TestClient, make_tenant: Any
) -> None:
    await make_tenant("local")
    resp = client_with_db.post(
        "/api/v1/semantic/query",
        headers=_auth(),
        json={"measures": ["regional_sales.secret"], "dimensions": []},
    )
    assert resp.status_code == 422, resp.text
    assert "Unknown measure" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_query_requires_a_field(client_with_db: TestClient, make_tenant: Any) -> None:
    await make_tenant("local")
    resp = client_with_db.post(
        "/api/v1/semantic/query", headers=_auth(), json={"measures": [], "dimensions": []}
    )
    # Pydantic model-validator rejects an empty selection before any Cube call.
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_query_is_tenant_scoped(
    client_with_db: TestClient, make_tenant: Any, fake_cube: _FakeCube
) -> None:
    await make_tenant("local")
    await make_tenant("other")
    body = {
        "measures": ["regional_sales.total_amount"],
        "dimensions": ["regional_sales.region"],
    }
    assert (
        client_with_db.post("/api/v1/semantic/query", headers=_auth("local"), json=body).status_code
        == 200
    )
    assert (
        client_with_db.post("/api/v1/semantic/query", headers=_auth("other"), json=body).status_code
        == 200
    )
    # The two tenants resolved to two different ClickHouse databases — the scope
    # the Cube JWT is minted from, never the request body.
    assert len(set(fake_cube.seen_dbs)) == 2
