"""Tests for the Phase 1 definition-registry ORM models.

Exercises insert/roundtrip, the relationship graph (pipeline→runs,
dashboard→tiles, dbt_model→tests), tenant scoping, and cascade deletes — using the
in-memory SQLite schema built from ``Base.metadata`` (no live infra).
"""
from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Chart,
    Dashboard,
    DashboardTile,
    DbtModel,
    DbtTest,
    Pipeline,
    PipelineRun,
    SemanticModel,
    SourceConnection,
    Tenant,
)


@pytest.mark.asyncio
async def test_source_pipeline_run_graph(
    session: AsyncSession, make_tenant: Any
) -> None:
    tenant: Tenant = await make_tenant("acme")
    src = SourceConnection(
        tenant_id=tenant.id, name="warehouse", kind="sql_database",
        config={"host": "db", "database": "sales"},
    )
    session.add(src)
    await session.flush()

    pipeline = Pipeline(
        tenant_id=tenant.id, source_connection_id=src.id, name="load orders",
        config={"tables": ["orders"], "write_disposition": "replace"},
        target_table="orders_raw",
    )
    pipeline.runs.append(PipelineRun(tenant_id=tenant.id, status="success", rows=42))
    session.add(pipeline)
    await session.flush()

    loaded = (
        await session.execute(select(Pipeline).where(Pipeline.id == pipeline.id))
    ).scalar_one()
    assert loaded.config["tables"] == ["orders"]
    assert loaded.enabled is True  # server_default applied
    assert len(loaded.runs) == 1
    assert loaded.runs[0].rows == 42


@pytest.mark.asyncio
async def test_dbt_model_tests_cascade(session: AsyncSession, make_tenant: Any) -> None:
    tenant: Tenant = await make_tenant("acme")
    model = DbtModel(tenant_id=tenant.id, name="mart_orders", layer="marts")
    model.tests.append(DbtTest(tenant_id=tenant.id, column_name="id", test_type="not_null"))
    model.tests.append(DbtTest(tenant_id=tenant.id, column_name="id", test_type="unique"))
    session.add(model)
    await session.flush()

    assert len(model.tests) == 2
    await session.delete(model)
    await session.flush()
    remaining = (await session.execute(select(DbtTest))).scalars().all()
    assert remaining == []  # cascade removed the child tests


@pytest.mark.asyncio
async def test_dashboard_tiles_ordered_and_defaults(
    session: AsyncSession, make_tenant: Any
) -> None:
    tenant: Tenant = await make_tenant("acme")
    chart = Chart(
        tenant_id=tenant.id, name="rev by region",
        spec={"version": "1", "type": "bar", "query": {}, "encoding": {"series": []}},
        source_kind="semantic", source_ref="sm-1",
    )
    session.add(chart)
    await session.flush()

    dash = Dashboard(tenant_id=tenant.id, name="Exec")
    dash.tiles.append(DashboardTile(tenant_id=tenant.id, chart_id=chart.id, position=1))
    dash.tiles.append(DashboardTile(tenant_id=tenant.id, chart_id=chart.id, position=0))
    session.add(dash)
    await session.flush()
    dash_id = dash.id  # capture before expiring (avoids a sync lazy reload)
    session.expire(dash)

    loaded = (
        await session.execute(
            select(Dashboard)
            .where(Dashboard.id == dash_id)
            .options(selectinload(Dashboard.tiles))
        )
    ).scalar_one()
    # relationship order_by position
    assert [t.position for t in loaded.tiles] == [0, 1]
    # default grid size from server_default
    assert loaded.tiles[0].w == 6 and loaded.tiles[0].h == 4
    assert loaded.tiles[0].chart_id == chart.id


@pytest.mark.asyncio
async def test_registry_is_tenant_scoped(session: AsyncSession, make_tenant: Any) -> None:
    a: Tenant = await make_tenant("alpha")
    b: Tenant = await make_tenant("beta")
    session.add(SemanticModel(tenant_id=a.id, name="orders", base_table="serving_orders"))
    session.add(SemanticModel(tenant_id=b.id, name="orders", base_table="serving_orders"))
    await session.flush()

    a_models = (
        await session.execute(select(SemanticModel).where(SemanticModel.tenant_id == a.id))
    ).scalars().all()
    assert len(a_models) == 1
    assert a_models[0].tenant_id == a.id
    # Same name in two tenants is allowed (scoped, not globally unique).
    assert a_models[0].tenant_id != b.id


@pytest.mark.asyncio
async def test_secret_ciphertext_is_optional(session: AsyncSession, make_tenant: Any) -> None:
    tenant: Tenant = await make_tenant("acme")
    src = SourceConnection(
        tenant_id=tenant.id, name="public api", kind="filesystem", config={"path": "/data"}
    )
    session.add(src)
    await session.flush()
    assert src.secret_ciphertext is None
    assert isinstance(src.id, uuid.UUID)
