"""Native-filter persistence + the removal of the 'filter' tile kind (Slice C)."""
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import FAKE_ENV
from tests.conftest import auth_headers as _auth


@pytest.fixture(autouse=True)
def _patch_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in FAKE_ENV.items():
        monkeypatch.setenv(k, v)


@pytest.mark.asyncio
async def test_dashboard_round_trips_native_filters(
    client_with_db: TestClient, make_tenant: Any
) -> None:
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
    created = client_with_db.post("/api/v1/dashboards", headers=_auth(), json={"name": "D"})
    did = created.json()["id"]
    resp = client_with_db.post(
        f"/api/v1/dashboards/{did}/tiles", headers=_auth(),
        json={"kind": "filter", "content": {"member": "regional_sales.region"}},
    )
    assert resp.status_code == 422, resp.text
