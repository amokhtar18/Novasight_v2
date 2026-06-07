"""Tests for the semantic-model registry API (#8).

Password (HS256) mode; CUBE__MODEL_DIR points at a tmp dir so codegen actually
writes. Covers superuser gating, CRUD, name uniqueness, codegen regeneration
(the tenant's Cube file is written with the isolation guard), and tenant isolation
(another tenant's model is 404; each tenant's codegen targets its own db file).
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.tenancy.resources import resources_for_slug

_SESSION_SECRET = "test-session-secret-do-not-use-in-production-0123456789"


def _base_env() -> dict[str, str]:
    return {
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


@pytest.fixture()
def model_dir(tmp_path: Path) -> Path:
    return tmp_path / "model"


@pytest.fixture(autouse=True)
def _patch_env(monkeypatch: pytest.MonkeyPatch, model_dir: Path) -> None:
    for key, value in _base_env().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("CUBE__MODEL_DIR", str(model_dir))


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


SU = ["superuser"]


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


def _model_body(name: str = "sales") -> dict[str, Any]:
    return {
        "name": name,
        "base_table": "mart_sales",
        "config": {
            "measures": [{"name": "total_amount", "type": "sum", "sql": "amount"}],
            "dimensions": [{"name": "region", "type": "string", "sql": "region"}],
        },
    }


@pytest.mark.asyncio
async def test_create_requires_superuser(client_with_db: TestClient, make_tenant: Any) -> None:
    await make_tenant("local")
    resp = client_with_db.post("/api/v1/semantic-models", headers=_auth(), json=_model_body())
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_writes_codegen_and_round_trips(
    client_with_db: TestClient, make_tenant: Any, model_dir: Path
) -> None:
    await make_tenant("local")
    resp = client_with_db.post(
        "/api/v1/semantic-models", headers=_auth("local", SU), json=_model_body()
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "sales"
    assert body["config"]["measures"][0]["name"] == "total_amount"

    # Codegen wrote this tenant's Cube file into its own subdir (dir-isolated).
    db = resources_for_slug("local").clickhouse_db
    generated = (model_dir / db / "models.js").read_text(encoding="utf-8")
    assert "cube(`sales`" in generated
    assert "mart_sales" in generated
    assert "if (COMPILE_CONTEXT" not in generated  # no in-file guard with subdirs

    got = client_with_db.get(f"/api/v1/semantic-models/{body['id']}", headers=_auth())
    assert got.status_code == 200


@pytest.mark.asyncio
async def test_duplicate_name_conflicts(client_with_db: TestClient, make_tenant: Any) -> None:
    await make_tenant("local")
    client_with_db.post("/api/v1/semantic-models", headers=_auth("local", SU), json=_model_body())
    dup = client_with_db.post(
        "/api/v1/semantic-models", headers=_auth("local", SU), json=_model_body()
    )
    assert dup.status_code == 409


@pytest.mark.asyncio
async def test_delete_regenerates_without_the_model(
    client_with_db: TestClient, make_tenant: Any, model_dir: Path
) -> None:
    await make_tenant("local")
    mid = client_with_db.post(
        "/api/v1/semantic-models", headers=_auth("local", SU), json=_model_body()
    ).json()["id"]
    db = resources_for_slug("local").clickhouse_db
    assert "cube(`sales`" in (model_dir / db / "models.js").read_text(encoding="utf-8")

    assert (
        client_with_db.delete(
            f"/api/v1/semantic-models/{mid}", headers=_auth("local", SU)
        ).status_code
        == 204
    )
    # The cube is gone from the regenerated file (file remains, no cubes).
    assert "cube(`sales`" not in (model_dir / db / "models.js").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_tenant_isolation(
    client_with_db: TestClient, make_tenant: Any, model_dir: Path
) -> None:
    await make_tenant("local")
    await make_tenant("other")
    mid = client_with_db.post(
        "/api/v1/semantic-models", headers=_auth("local", SU), json=_model_body()
    ).json()["id"]

    # other can't see local's model.
    assert client_with_db.get("/api/v1/semantic-models", headers=_auth("other")).json() == []
    other_get = client_with_db.get(f"/api/v1/semantic-models/{mid}", headers=_auth("other", SU))
    assert other_get.status_code == 404

    # Each tenant's codegen targets its own per-tenant subdir (dir-level isolation).
    local_db = resources_for_slug("local").clickhouse_db
    other_db = resources_for_slug("other").clickhouse_db
    assert (model_dir / local_db / "models.js").exists()
    local_js = (model_dir / local_db / "models.js").read_text(encoding="utf-8")
    assert "cube(`sales`" in local_js
    assert other_db not in local_js
