"""Tests for the dbt model registry API (#5/#6).

CUBE/DBT model dirs point at a tmp dir so codegen writes. Covers superuser gating,
CRUD with nested tests, name uniqueness, codegen regeneration (the tenant subtree is
written), and tenant isolation.
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
SU = ["superuser"]


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
def dbt_dir(tmp_path: Path) -> Path:
    return tmp_path / "dbt-models"


@pytest.fixture(autouse=True)
def _patch_env(monkeypatch: pytest.MonkeyPatch, dbt_dir: Path) -> None:
    for key, value in _base_env().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("DBT__MODELS_DIR", str(dbt_dir))


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
        "sub": "caller", "email": "c@x", "tenant": tenant,
        "roles": roles or [], "typ": "access", "exp": int(time.time()) + 3600,
    }
    return {"Authorization": f"Bearer {jwt.encode(payload, _SESSION_SECRET, algorithm='HS256')}"}


def _body(name: str = "mart_orders") -> dict[str, Any]:
    return {
        "name": name,
        "layer": "marts",
        "materialization": "table",
        "sql": "select region, sum(amount) as total from {{ ref('stg_orders') }} group by 1",
        "tests": [
            {"column_name": "region", "test_type": "not_null"},
            {"column_name": "region", "test_type": "unique"},
        ],
    }


@pytest.mark.asyncio
async def test_create_requires_superuser(client_with_db: TestClient, make_tenant: Any) -> None:
    await make_tenant("local")
    resp = client_with_db.post("/api/v1/dbt-models", headers=_auth(), json=_body())
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_writes_codegen_and_round_trips(
    client_with_db: TestClient, make_tenant: Any, dbt_dir: Path
) -> None:
    await make_tenant("local")
    resp = client_with_db.post("/api/v1/dbt-models", headers=_auth("local", SU), json=_body())
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "mart_orders"
    assert len(body["tests"]) == 2

    schema = resources_for_slug("local").dbt_schema
    tdir = dbt_dir / f"tenant_{schema}"
    sql = (tdir / "mart_orders.sql").read_text(encoding="utf-8")
    assert "config(materialized='table')" in sql
    assert (tdir / "schema.yml").exists()

    got = client_with_db.get(f"/api/v1/dbt-models/{body['id']}", headers=_auth())
    assert got.status_code == 200


@pytest.mark.asyncio
async def test_duplicate_name_conflicts(client_with_db: TestClient, make_tenant: Any) -> None:
    await make_tenant("local")
    client_with_db.post("/api/v1/dbt-models", headers=_auth("local", SU), json=_body())
    dup = client_with_db.post("/api/v1/dbt-models", headers=_auth("local", SU), json=_body())
    assert dup.status_code == 409


@pytest.mark.asyncio
async def test_update_replaces_tests(client_with_db: TestClient, make_tenant: Any) -> None:
    await make_tenant("local")
    mid = client_with_db.post(
        "/api/v1/dbt-models", headers=_auth("local", SU), json=_body()
    ).json()["id"]
    upd = client_with_db.patch(
        f"/api/v1/dbt-models/{mid}",
        headers=_auth("local", SU),
        json={"tests": [{"column_name": "total", "test_type": "not_null"}]},
    )
    assert upd.status_code == 200
    assert len(upd.json()["tests"]) == 1
    assert upd.json()["tests"][0]["column_name"] == "total"


@pytest.mark.asyncio
async def test_tenant_isolation(
    client_with_db: TestClient, make_tenant: Any, dbt_dir: Path
) -> None:
    await make_tenant("local")
    await make_tenant("other")
    mid = client_with_db.post(
        "/api/v1/dbt-models", headers=_auth("local", SU), json=_body()
    ).json()["id"]

    assert client_with_db.get("/api/v1/dbt-models", headers=_auth("other")).json() == []
    other_get = client_with_db.get(f"/api/v1/dbt-models/{mid}", headers=_auth("other", SU))
    assert other_get.status_code == 404

    # Each tenant's codegen targets its own subdir.
    local_schema = resources_for_slug("local").dbt_schema
    assert (dbt_dir / f"tenant_{local_schema}" / "mart_orders.sql").exists()
