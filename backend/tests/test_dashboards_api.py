"""Tests for the dashboards API (#10 — dashboard persistence).

Dashboards and their tiles persist to Postgres, scoped to a tenant. Covers
create/get/update/delete, pinning a saved chart as a tile (with a server-side
chart-ownership check), layout persistence, and tenant isolation — a dashboard,
tile, or chart from another tenant is indistinguishable from not-found (404).
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


def _spec() -> dict[str, Any]:
    return {
        "version": "1",
        "type": "bar",
        "query": {"metric_refs": ["regional_sales.total_amount"]},
        "encoding": {
            "x": "regional_sales.region",
            "series": [{"field": "regional_sales.total_amount", "name": "Total"}],
        },
        "options": {"title": "Total by region"},
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


def _auth(tenant: str = "local", roles: list[str] | None = None) -> dict[str, str]:
    payload = {
        "sub": "caller",
        "email": "c@x",
        "tenant": tenant,
        "roles": roles or [],
        "typ": "access",
        "exp": int(time.time()) + 3600,
    }
    return {"Authorization": f"Bearer {jwt.encode(payload, _SESSION_SECRET, algorithm='HS256')}"}


@pytest.mark.asyncio
async def test_viewer_is_read_only(client_with_db: TestClient, make_tenant: Any) -> None:
    await make_tenant("local")
    viewer = _auth("local", ["viewer"])
    did = client_with_db.post(
        "/api/v1/dashboards", headers=_auth(), json={"name": "Overview"}
    ).json()["id"]
    # A read-only viewer cannot create or modify dashboards…
    create = client_with_db.post("/api/v1/dashboards", headers=viewer, json={"name": "X"})
    assert create.status_code == 403
    patch = client_with_db.patch(
        f"/api/v1/dashboards/{did}", headers=viewer, json={"name": "Y"}
    )
    assert patch.status_code == 403
    # …but can still read them.
    assert client_with_db.get("/api/v1/dashboards", headers=viewer).status_code == 200
    assert client_with_db.get(f"/api/v1/dashboards/{did}", headers=viewer).status_code == 200


def _make_chart(client: TestClient, tenant: str = "local", name: str = "Sales") -> str:
    resp = client.post(
        "/api/v1/charts",
        headers=_auth(tenant),
        json={"name": name, "spec": _spec(), "source_kind": "semantic",
              "source_ref": "regional_sales"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_filters_persist_and_round_trip(
    client_with_db: TestClient, make_tenant: Any
) -> None:
    await make_tenant("local")
    did = client_with_db.post(
        "/api/v1/dashboards", headers=_auth(), json={"name": "Sales"}
    ).json()["id"]
    # A new dashboard has no filters.
    assert client_with_db.get(f"/api/v1/dashboards/{did}", headers=_auth()).json()["filters"] == []

    # PATCH persists a filter; GET returns it.
    patch = client_with_db.patch(
        f"/api/v1/dashboards/{did}",
        headers=_auth(),
        json={
            "filters": [
                {"member": "regional_sales.region", "operator": "equals", "values": ["west"]}
            ]
        },
    )
    assert patch.status_code == 200, patch.text
    got = client_with_db.get(f"/api/v1/dashboards/{did}", headers=_auth()).json()
    assert got["filters"] == [
        {"member": "regional_sales.region", "operator": "equals", "values": ["west"]}
    ]

    # Filters can be cleared with an empty list.
    client_with_db.patch(f"/api/v1/dashboards/{did}", headers=_auth(), json={"filters": []})
    assert client_with_db.get(f"/api/v1/dashboards/{did}", headers=_auth()).json()["filters"] == []


@pytest.mark.asyncio
async def test_create_pin_and_get(client_with_db: TestClient, make_tenant: Any) -> None:
    await make_tenant("local")
    chart_id = _make_chart(client_with_db)

    dash = client_with_db.post(
        "/api/v1/dashboards", headers=_auth(), json={"name": "Overview"}
    )
    assert dash.status_code == 201, dash.text
    did = dash.json()["id"]
    assert dash.json()["tiles"] == []

    tile = client_with_db.post(
        f"/api/v1/dashboards/{did}/tiles",
        headers=_auth(),
        json={"chart_id": chart_id, "title": "Region totals"},
    )
    assert tile.status_code == 201, tile.text
    assert tile.json()["chart"]["id"] == chart_id

    # Detail embeds the tile + its chart spec (one round-trip render).
    got = client_with_db.get(f"/api/v1/dashboards/{did}", headers=_auth())
    assert got.status_code == 200
    body = got.json()
    assert len(body["tiles"]) == 1
    assert body["tiles"][0]["title"] == "Region totals"
    assert body["tiles"][0]["chart"]["spec"]["encoding"]["x"] == "regional_sales.region"

    # Summary list reports the tile count without embedding tiles.
    summary = client_with_db.get("/api/v1/dashboards", headers=_auth()).json()
    assert summary[0]["tile_count"] == 1


@pytest.mark.asyncio
async def test_decoration_tiles(client_with_db: TestClient, make_tenant: Any) -> None:
    # Non-chart tiles (#10): a text tile carries content + a null chart; a chart tile
    # without chart_id is rejected.
    await make_tenant("local")
    dash = client_with_db.post(
        "/api/v1/dashboards", headers=_auth(), json={"name": "Mixed"}
    )
    did = dash.json()["id"]

    text_tile = client_with_db.post(
        f"/api/v1/dashboards/{did}/tiles",
        headers=_auth(),
        json={"kind": "text", "content": {"text": "Quarterly review"}, "title": "Note"},
    )
    assert text_tile.status_code == 201, text_tile.text
    body = text_tile.json()
    assert body["kind"] == "text"
    assert body["chart"] is None
    assert body["content"] == {"text": "Quarterly review"}

    # A chart tile still requires a chart_id (validator → 422).
    bad = client_with_db.post(
        f"/api/v1/dashboards/{did}/tiles",
        headers=_auth(),
        json={"kind": "chart"},
    )
    assert bad.status_code == 422

    got = client_with_db.get(f"/api/v1/dashboards/{did}", headers=_auth()).json()
    assert got["tiles"][0]["kind"] == "text"


@pytest.mark.asyncio
async def test_add_tile_rejects_cross_tenant_chart(
    client_with_db: TestClient, make_tenant: Any
) -> None:
    await make_tenant("local")
    await make_tenant("other")
    local_chart = _make_chart(client_with_db, "local")
    other_dash = client_with_db.post(
        "/api/v1/dashboards", headers=_auth("other"), json={"name": "Theirs"}
    ).json()["id"]

    # "other" cannot pin "local"'s chart — 404 (indistinguishable from missing).
    resp = client_with_db.post(
        f"/api/v1/dashboards/{other_dash}/tiles",
        headers=_auth("other"),
        json={"chart_id": local_chart},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_layout_and_tile_delete(client_with_db: TestClient, make_tenant: Any) -> None:
    await make_tenant("local")
    did = client_with_db.post(
        "/api/v1/dashboards", headers=_auth(), json={"name": "Grid"}
    ).json()["id"]
    t1 = client_with_db.post(
        f"/api/v1/dashboards/{did}/tiles", headers=_auth(),
        json={"chart_id": _make_chart(client_with_db, name="A")},
    ).json()
    t2 = client_with_db.post(
        f"/api/v1/dashboards/{did}/tiles", headers=_auth(),
        json={"chart_id": _make_chart(client_with_db, name="B")},
    ).json()

    # Persist a reordered/resized layout (t2 first, wide).
    layout = client_with_db.put(
        f"/api/v1/dashboards/{did}/layout",
        headers=_auth(),
        json={"tiles": [
            {"id": t2["id"], "position": 0, "w": 12, "h": 4},
            {"id": t1["id"], "position": 1, "w": 6, "h": 4},
        ]},
    )
    assert layout.status_code == 200, layout.text
    tiles = layout.json()["tiles"]
    assert [t["id"] for t in tiles] == [t2["id"], t1["id"]]
    assert tiles[0]["w"] == 12

    # Delete a tile.
    assert (
        client_with_db.delete(
            f"/api/v1/dashboards/{did}/tiles/{t1['id']}", headers=_auth()
        ).status_code
        == 204
    )
    remaining = client_with_db.get(f"/api/v1/dashboards/{did}", headers=_auth()).json()
    assert len(remaining["tiles"]) == 1


@pytest.mark.asyncio
async def test_tenant_isolation(client_with_db: TestClient, make_tenant: Any) -> None:
    await make_tenant("local")
    await make_tenant("other")
    did = client_with_db.post(
        "/api/v1/dashboards", headers=_auth("local"), json={"name": "Mine"}
    ).json()["id"]

    # other sees none and cannot get/delete local's dashboard.
    assert client_with_db.get("/api/v1/dashboards", headers=_auth("other")).json() == []
    other_get = client_with_db.get(f"/api/v1/dashboards/{did}", headers=_auth("other"))
    assert other_get.status_code == 404
    other_del = client_with_db.delete(f"/api/v1/dashboards/{did}", headers=_auth("other"))
    assert other_del.status_code == 404
    # local's dashboard is untouched.
    local_get = client_with_db.get(f"/api/v1/dashboards/{did}", headers=_auth("local"))
    assert local_get.status_code == 200
