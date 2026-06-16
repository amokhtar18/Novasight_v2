"""Tests for the dbt model run endpoint (``POST /dbt-models/{id}/run``, #7 app slice).

A fake Dagster client records launches (no live orchestrator), so the real
``TransformService`` logic — tenant-scoped model resolution and find-or-create of the
``TransformJob`` registry row — is exercised against the test DB. Covers superuser
gating, the launch + run-config contract, transform-job reuse, disabled/unknown/cross
-tenant handling, and the DagsterError → 503 mapping.
"""
from __future__ import annotations

import time
import uuid
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dbt_model import DbtModel
from app.models.transform_job import TransformJob
from app.orchestration.dagster_client import DagsterError

_SESSION_SECRET = "test-session-secret-do-not-use-in-production-0123456789"
SU = ["superuser"]

_ENV: dict[str, str] = {
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


class _FakeDagster:
    """Records launches and returns a fixed run id (or raises, to test 503)."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    async def launch_run(self, *, job_name: str, run_config: dict[str, Any]) -> str:
        if self.fail:
            raise DagsterError("Dagster is unavailable")
        self.calls.append({"job_name": job_name, "run_config": run_config})
        return "dagster-run-123"


@pytest.fixture(autouse=True)
def _patch_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _ENV.items():
        monkeypatch.setenv(key, value)


@pytest.fixture()
def dagster() -> _FakeDagster:
    return _FakeDagster()


@pytest.fixture()
def client_with_db(session: AsyncSession, dagster: _FakeDagster) -> TestClient:  # type: ignore[return]
    from app.core.config import get_settings
    from app.core.db import get_db
    from app.main import app
    from app.orchestration.dagster_client import get_dagster_client
    from app.tenancy.registry import TenantRegistry, get_tenant_registry

    get_settings.cache_clear()

    async def _fake_db() -> Any:
        yield session

    async def _fake_registry() -> Any:
        return TenantRegistry(session)

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_tenant_registry] = _fake_registry
    app.dependency_overrides[get_dagster_client] = lambda: dagster

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


async def _make_model(
    session: AsyncSession, tenant: Any, name: str = "mart_orders", *, enabled: bool = True
) -> str:
    model = DbtModel(
        tenant_id=tenant.id, name=name, layer="marts", materialization="table",
        sql="select 1", config={}, enabled=enabled,
    )
    session.add(model)
    await session.flush()
    return str(model.id)


async def _transform_jobs(session: AsyncSession) -> list[TransformJob]:
    return list((await session.execute(select(TransformJob))).scalars().all())


@pytest.mark.asyncio
async def test_run_requires_superuser(client_with_db: TestClient, make_tenant: Any) -> None:
    await make_tenant("local")
    resp = client_with_db.post(f"/api/v1/dbt-models/{uuid.uuid4()}/run", headers=_auth())
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_run_launches_transform_and_creates_job(
    client_with_db: TestClient, make_tenant: Any, session: AsyncSession, dagster: _FakeDagster
) -> None:
    tenant = await make_tenant("local")
    mid = await _make_model(session, tenant, "mart_orders")

    resp = client_with_db.post(f"/api/v1/dbt-models/{mid}/run", headers=_auth("local", SU))
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["dagster_run_id"] == "dagster-run-123"
    assert body["selection"] == "mart_orders"

    # A transform job was created for the model's selector, scoped to the tenant.
    jobs = await _transform_jobs(session)
    assert len(jobs) == 1
    assert jobs[0].selection == "mart_orders"
    assert str(jobs[0].tenant_id) == str(tenant.id)

    # Dagster was launched with the generic transform job + the contract run-config.
    assert len(dagster.calls) == 1
    call = dagster.calls[0]
    assert call["job_name"] == "transform_job"
    cfg = call["run_config"]["ops"]["run_transform"]["config"]
    assert cfg["transform_job_id"] == body["transform_job_id"]
    assert cfg["tenant"] == "local"  # the slug, from the verified principal


@pytest.mark.asyncio
async def test_run_reuses_transform_job(
    client_with_db: TestClient, make_tenant: Any, session: AsyncSession
) -> None:
    tenant = await make_tenant("local")
    mid = await _make_model(session, tenant, "mart_orders")

    first = client_with_db.post(f"/api/v1/dbt-models/{mid}/run", headers=_auth("local", SU))
    second = client_with_db.post(f"/api/v1/dbt-models/{mid}/run", headers=_auth("local", SU))
    assert first.status_code == second.status_code == 202
    # Same selection → one row reused, not duplicated.
    assert first.json()["transform_job_id"] == second.json()["transform_job_id"]
    assert len(await _transform_jobs(session)) == 1


@pytest.mark.asyncio
async def test_run_unknown_model_404(client_with_db: TestClient, make_tenant: Any) -> None:
    await make_tenant("local")
    resp = client_with_db.post(f"/api/v1/dbt-models/{uuid.uuid4()}/run", headers=_auth("local", SU))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_run_disabled_model_409(
    client_with_db: TestClient, make_tenant: Any, session: AsyncSession
) -> None:
    tenant = await make_tenant("local")
    mid = await _make_model(session, tenant, "mart_off", enabled=False)
    resp = client_with_db.post(f"/api/v1/dbt-models/{mid}/run", headers=_auth("local", SU))
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_run_orchestrator_unavailable_503(
    session: AsyncSession, make_tenant: Any
) -> None:
    # A failing Dagster client surfaces as 503, never a raw 500.
    from app.core.config import get_settings
    from app.core.db import get_db
    from app.main import app
    from app.orchestration.dagster_client import get_dagster_client
    from app.tenancy.registry import TenantRegistry, get_tenant_registry

    get_settings.cache_clear()
    tenant = await make_tenant("local")
    mid = await _make_model(session, tenant, "mart_orders")

    async def _fake_db() -> Any:
        yield session

    async def _fake_registry() -> Any:
        return TenantRegistry(session)

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_tenant_registry] = _fake_registry
    app.dependency_overrides[get_dagster_client] = lambda: _FakeDagster(fail=True)
    try:
        with TestClient(app, raise_server_exceptions=True) as c:
            resp = c.post(f"/api/v1/dbt-models/{mid}/run", headers=_auth("local", SU))
        assert resp.status_code == 503
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_run_tenant_isolation(
    client_with_db: TestClient, make_tenant: Any, session: AsyncSession
) -> None:
    local = await make_tenant("local")
    await make_tenant("other")
    mid = await _make_model(session, local, "mart_orders")
    # "other" cannot run local's model — 404 (indistinguishable from missing).
    resp = client_with_db.post(f"/api/v1/dbt-models/{mid}/run", headers=_auth("other", SU))
    assert resp.status_code == 404
