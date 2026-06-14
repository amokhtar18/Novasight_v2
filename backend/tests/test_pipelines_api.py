"""Tests for the pipelines API (#3) — CRUD, run history, run-now, isolation.

run-now enqueues via an injected fake (no broker). A source connection is seeded
directly. Covers superuser gating, cross-tenant source rejection, run-now creating a
queued run + enqueuing, and tenant isolation (another tenant's pipeline is 404).
"""
from __future__ import annotations

import time
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.source_connection import SourceConnection

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

SU = ["superuser"]


@pytest.fixture(autouse=True)
def _patch_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _FAKE_ENV.items():
        monkeypatch.setenv(key, value)


@pytest.fixture()
def enqueued() -> list[str]:
    return []


@pytest.fixture()
def client_with_db(session: AsyncSession, enqueued: list[str]) -> TestClient:  # type: ignore[return]
    from app.core.config import get_settings
    from app.core.db import get_db
    from app.main import app
    from app.services.pipelines import PipelineService, get_pipeline_service
    from app.tenancy.registry import TenantRegistry, get_tenant_registry

    get_settings.cache_clear()

    async def _fake_db() -> Any:
        yield session

    async def _fake_registry() -> Any:
        return TenantRegistry(session)

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_tenant_registry] = _fake_registry
    # Inject a fake enqueue so run-now needs no broker; record enqueued run ids.
    app.dependency_overrides[get_pipeline_service] = lambda: PipelineService(
        db=session, enqueue=enqueued.append
    )

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


async def _make_source(session: AsyncSession, tenant: Any, name: str = "db") -> str:
    source = SourceConnection(
        tenant_id=tenant.id, name=name, kind="sql_database",
        config={"driver": "sqlite", "database": "x"},
    )
    session.add(source)
    await session.flush()
    return str(source.id)


def _body(source_id: str, name: str = "orders_pipe") -> dict[str, Any]:
    return {
        "name": name,
        "source_connection_id": source_id,
        "config": {"object": "orders", "write_disposition": "overwrite"},
        "target_table": "orders",
    }


@pytest.mark.asyncio
async def test_create_requires_superuser(
    client_with_db: TestClient, make_tenant: Any, session: AsyncSession
) -> None:
    tenant = await make_tenant("local")
    sid = await _make_source(session, tenant)
    resp = client_with_db.post("/api/v1/pipelines", headers=_auth(), json=_body(sid))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_get_and_run_now(
    client_with_db: TestClient, make_tenant: Any, session: AsyncSession, enqueued: list[str]
) -> None:
    tenant = await make_tenant("local")
    sid = await _make_source(session, tenant)

    created = client_with_db.post("/api/v1/pipelines", headers=_auth("local", SU), json=_body(sid))
    assert created.status_code == 201, created.text
    pid = created.json()["id"]
    assert created.json()["config"]["object"] == "orders"

    assert client_with_db.get(f"/api/v1/pipelines/{pid}", headers=_auth()).status_code == 200

    # run-now: creates a queued run, returns 202, and enqueues exactly that run id.
    run = client_with_db.post(f"/api/v1/pipelines/{pid}/run", headers=_auth("local", SU))
    assert run.status_code == 202, run.text
    assert run.json()["status"] == "queued"
    assert enqueued == [run.json()["id"]]

    # run history shows it.
    runs = client_with_db.get(f"/api/v1/pipelines/{pid}/runs", headers=_auth()).json()
    assert len(runs) == 1 and runs[0]["status"] == "queued"


@pytest.mark.asyncio
async def test_recent_runs_feed_and_isolation(
    client_with_db: TestClient, make_tenant: Any, session: AsyncSession
) -> None:
    local = await make_tenant("local")
    await make_tenant("other")
    local_src = await _make_source(session, local)

    pid = client_with_db.post(
        "/api/v1/pipelines", headers=_auth("local", SU), json=_body(local_src, "local_pipe")
    ).json()["id"]
    run = client_with_db.post(f"/api/v1/pipelines/{pid}/run", headers=_auth("local", SU)).json()

    # The literal /runs segment resolves to the feed (not parsed as a pipeline id).
    feed = client_with_db.get("/api/v1/pipelines/runs", headers=_auth("local"))
    assert feed.status_code == 200, feed.text
    body = feed.json()
    assert len(body) == 1
    assert body[0]["id"] == run["id"]
    assert body[0]["pipeline_name"] == "local_pipe"  # joined name present

    # Another tenant sees none of local's runs.
    assert client_with_db.get("/api/v1/pipelines/runs", headers=_auth("other")).json() == []


@pytest.mark.asyncio
async def test_create_rejects_cross_tenant_source(
    client_with_db: TestClient, make_tenant: Any, session: AsyncSession
) -> None:
    local = await make_tenant("local")
    await make_tenant("other")
    local_source = await _make_source(session, local)
    # "other" cannot bind local's source — 404 (indistinguishable from missing).
    resp = client_with_db.post(
        "/api/v1/pipelines", headers=_auth("other", SU), json=_body(local_source)
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_update_delete_and_isolation(
    client_with_db: TestClient, make_tenant: Any, session: AsyncSession
) -> None:
    local = await make_tenant("local")
    await make_tenant("other")
    sid = await _make_source(session, local)
    pid = client_with_db.post(
        "/api/v1/pipelines", headers=_auth("local", SU), json=_body(sid)
    ).json()["id"]

    assert len(client_with_db.get("/api/v1/pipelines", headers=_auth("local")).json()) == 1

    upd = client_with_db.patch(
        f"/api/v1/pipelines/{pid}", headers=_auth("local", SU), json={"enabled": False}
    )
    assert upd.json()["enabled"] is False

    # A disabled pipeline can't be run.
    assert (
        client_with_db.post(f"/api/v1/pipelines/{pid}/run", headers=_auth("local", SU)).status_code
        == 409
    )

    # other can't see/delete local's pipeline.
    assert client_with_db.get("/api/v1/pipelines", headers=_auth("other")).json() == []
    assert client_with_db.get(f"/api/v1/pipelines/{pid}", headers=_auth("other")).status_code == 404
    other_del = client_with_db.delete(f"/api/v1/pipelines/{pid}", headers=_auth("other", SU))
    assert other_del.status_code == 404

    assert (
        client_with_db.delete(f"/api/v1/pipelines/{pid}", headers=_auth("local", SU)).status_code
        == 204
    )
