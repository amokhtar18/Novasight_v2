"""Tests for pipeline schedules (#4) — API CRUD + due dispatch + cron validation.

The API test covers superuser gating, cron validation (422), cross-tenant target
rejection, and isolation. A direct service test covers ``create_due_runs``: it
creates + enqueues a queued run for a due schedule and skips a disabled pipeline.
"""
from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline import Pipeline
from app.models.schedule import Schedule
from app.models.schedule_pipeline import SchedulePipeline
from app.services.schedules import ScheduleService

_SESSION_SECRET = "test-session-secret-do-not-use-in-production-0123456789"
SU = ["superuser"]

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
        "sub": "caller", "email": "c@x", "tenant": tenant,
        "roles": roles or [], "typ": "access", "exp": int(time.time()) + 3600,
    }
    return {"Authorization": f"Bearer {jwt.encode(payload, _SESSION_SECRET, algorithm='HS256')}"}


async def _make_pipeline(session: AsyncSession, tenant: Any, *, enabled: bool = True) -> Pipeline:
    from app.models.source_connection import SourceConnection

    source = SourceConnection(
        tenant_id=tenant.id, name="db", kind="sql_database",
        config={"driver": "sqlite", "database": "x"},
    )
    session.add(source)
    await session.flush()
    pipeline = Pipeline(
        tenant_id=tenant.id,
        source_connection_id=source.id,
        name="p",
        config={"object": "orders", "write_disposition": "overwrite"},
        target_table="orders",
        enabled=enabled,
    )
    session.add(pipeline)
    await session.flush()
    return pipeline


@pytest.mark.asyncio
async def test_create_requires_superuser(
    client_with_db: TestClient, make_tenant: Any, session: AsyncSession
) -> None:
    tenant = await make_tenant("local")
    p = await _make_pipeline(session, tenant)
    body = {"name": "nightly", "pipeline_ids": [str(p.id)], "cron": "0 2 * * *"}
    assert client_with_db.post("/api/v1/schedules", headers=_auth(), json=body).status_code == 403


@pytest.mark.asyncio
async def test_create_validates_cron(
    client_with_db: TestClient, make_tenant: Any, session: AsyncSession
) -> None:
    tenant = await make_tenant("local")
    p = await _make_pipeline(session, tenant)
    bad = {"name": "x", "pipeline_ids": [str(p.id)], "cron": "not a cron"}
    resp = client_with_db.post("/api/v1/schedules", headers=_auth("local", SU), json=bad)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_get_and_isolation(
    client_with_db: TestClient, make_tenant: Any, session: AsyncSession
) -> None:
    local = await make_tenant("local")
    await make_tenant("other")
    p = await _make_pipeline(session, local)

    created = client_with_db.post(
        "/api/v1/schedules",
        headers=_auth("local", SU),
        json={"name": "nightly", "pipeline_ids": [str(p.id)], "cron": "0 2 * * *"},
    )
    assert created.status_code == 201, created.text
    sid = created.json()["id"]
    # The created schedule echoes its attached pipelines (#3).
    assert created.json()["pipeline_ids"] == [str(p.id)]

    # other can't bind local's pipeline.
    cross = client_with_db.post(
        "/api/v1/schedules",
        headers=_auth("other", SU),
        json={"name": "x", "pipeline_ids": [str(p.id)], "cron": "0 2 * * *"},
    )
    assert cross.status_code == 404

    # other can't see local's schedule.
    assert client_with_db.get("/api/v1/schedules", headers=_auth("other")).json() == []
    assert client_with_db.get(f"/api/v1/schedules/{sid}", headers=_auth("other")).status_code == 404


@pytest.mark.asyncio
async def test_create_due_runs_enqueues_for_due_enabled_pipeline(
    make_tenant: Any, session: AsyncSession
) -> None:
    tenant = await make_tenant("local")
    enabled_pipe = await _make_pipeline(session, tenant, enabled=True)
    disabled_pipe = await _make_pipeline(session, tenant, enabled=False)
    # Every-minute cron → always due.
    due = Schedule(tenant_id=tenant.id, name="due", target_kind="pipeline",
                   target_id=enabled_pipe.id, cron="* * * * *", enabled=True)
    # Due, but its pipeline is disabled → skipped.
    skip = Schedule(tenant_id=tenant.id, name="skip", target_kind="pipeline",
                    target_id=disabled_pipe.id, cron="* * * * *", enabled=True)
    # Disabled schedule → never dispatched.
    off = Schedule(tenant_id=tenant.id, name="off", target_kind="pipeline",
                   target_id=enabled_pipe.id, cron="* * * * *", enabled=False)
    session.add_all([due, skip, off])
    await session.flush()
    # Fan-out reads the join table (#3): attach each schedule to its pipeline.
    session.add_all([
        SchedulePipeline(schedule_id=due.id, pipeline_id=enabled_pipe.id, tenant_id=tenant.id),
        SchedulePipeline(schedule_id=skip.id, pipeline_id=disabled_pipe.id, tenant_id=tenant.id),
        SchedulePipeline(schedule_id=off.id, pipeline_id=enabled_pipe.id, tenant_id=tenant.id),
    ])
    await session.flush()

    enqueued: list[str] = []
    run_ids = await ScheduleService(session).create_due_runs(
        datetime(2026, 1, 1, 12, 0, tzinfo=UTC), enqueued.append
    )

    # Exactly one run: the due, enabled schedule on the enabled pipeline.
    assert len(run_ids) == 1
    assert enqueued == [str(run_ids[0])]


@pytest.mark.asyncio
async def test_create_due_runs_fans_out_to_all_attached_pipelines(
    make_tenant: Any, session: AsyncSession
) -> None:
    # One reusable schedule attached to two enabled pipelines → two runs (#3).
    tenant = await make_tenant("local")
    p1 = await _make_pipeline(session, tenant, enabled=True)
    p2 = await _make_pipeline(session, tenant, enabled=True)
    sched = Schedule(tenant_id=tenant.id, name="nightly", target_kind="pipeline",
                     target_id=p1.id, cron="* * * * *", enabled=True)
    session.add(sched)
    await session.flush()
    session.add_all([
        SchedulePipeline(schedule_id=sched.id, pipeline_id=p1.id, tenant_id=tenant.id),
        SchedulePipeline(schedule_id=sched.id, pipeline_id=p2.id, tenant_id=tenant.id),
    ])
    await session.flush()

    enqueued: list[str] = []
    run_ids = await ScheduleService(session).create_due_runs(
        datetime(2026, 1, 1, 12, 0, tzinfo=UTC), enqueued.append
    )

    assert len(run_ids) == 2
    assert sorted(enqueued) == sorted(str(r) for r in run_ids)
