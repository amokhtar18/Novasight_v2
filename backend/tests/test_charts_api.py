"""Tests for the saved-chart API (#9 — chart persistence).

Charts persist a ``ChartSpec`` to Postgres, scoped to a tenant. Covers create/list/
get/update/delete, spec round-trip integrity, and tenant isolation (a chart owned by
another tenant is indistinguishable from not-found — 404, never a cross-tenant leak).
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import FAKE_ENV
from tests.conftest import auth_headers as _auth


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
    for key, value in FAKE_ENV.items():
        monkeypatch.setenv(key, value)


@pytest.mark.asyncio
async def test_viewer_is_read_only(client_with_db: TestClient, make_tenant: Any) -> None:
    await make_tenant("local")
    body = {
        "name": "X", "spec": _spec(), "source_kind": "semantic", "source_ref": "regional_sales",
    }
    viewer = _auth("local", ["viewer"])
    # A read-only viewer cannot create; a normal member (no roles) can.
    assert client_with_db.post("/api/v1/charts", headers=viewer, json=body).status_code == 403
    cid = client_with_db.post("/api/v1/charts", headers=_auth(), json=body).json()["id"]
    # A viewer can still read…
    assert client_with_db.get("/api/v1/charts", headers=viewer).status_code == 200
    # …but not delete.
    assert client_with_db.delete(f"/api/v1/charts/{cid}", headers=viewer).status_code == 403
    # A superuser who also holds viewer outranks the restriction.
    su = _auth("local", ["viewer", "superuser"])
    assert client_with_db.delete(f"/api/v1/charts/{cid}", headers=su).status_code == 204


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
