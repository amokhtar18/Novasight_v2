"""Tests for the PipelineExecutor orchestration (#3) — no live infra.

The three infra steps (extract/load/register) are injected fakes, so the run
lifecycle is exercised end-to-end: a happy run goes queued→running→success with rows
recorded; a failing step is captured as error on the run. Tenant scope is re-resolved
from the registry inside the executor (job context), exactly as in production.
"""
from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.pipeline_executor import PipelineExecutor
from app.models.pipeline import Pipeline, PipelineRun
from app.models.source_connection import SourceConnection
from app.tenancy.context import TenantContext


async def _seed(
    session: AsyncSession, tenant: Any, *, config: dict[str, Any] | None = None
) -> tuple[Pipeline, PipelineRun]:
    source = SourceConnection(
        tenant_id=tenant.id, name="db", kind="sql_database",
        config={"driver": "sqlite", "database": "x"},
    )
    session.add(source)
    await session.flush()
    pipeline = Pipeline(
        tenant_id=tenant.id,
        source_connection_id=source.id,
        name="orders_pipe",
        config=config or {"object": "orders", "write_disposition": "overwrite"},
        target_table="orders",
    )
    session.add(pipeline)
    await session.flush()
    run = PipelineRun(tenant_id=tenant.id, pipeline_id=pipeline.id, status="queued")
    session.add(run)
    await session.flush()
    return pipeline, run


def _executor(*, extract: Any = None, load: Any = None, register: Any = None) -> PipelineExecutor:
    async def _extract(
        ctx: TenantContext, source: Any, secret: Any, target: str, spec: Any
    ) -> Any:
        return "arrow-sentinel"

    def _load(ctx: TenantContext, table: str, arrow: Any, plan: Any) -> int:
        return 42

    def _register(ctx: TenantContext, table: str) -> str:
        return f"{ctx.clickhouse_db}.{table}"

    return PipelineExecutor(
        extract=extract or _extract,
        load=load or _load,
        register=register or _register,
        decrypt=lambda _token: None,
    )


@pytest.mark.asyncio
async def test_successful_run_records_rows_and_success(
    session: AsyncSession, make_tenant: Any
) -> None:
    tenant = await make_tenant("local")
    _pipeline, run = await _seed(session, tenant)

    captured: dict[str, Any] = {}

    def load(ctx: TenantContext, table: str, arrow: Any, plan: Any) -> int:
        captured["table"] = table
        captured["db"] = ctx.clickhouse_db
        captured["disposition"] = plan.disposition
        return 7

    await _executor(load=load).execute(session, run.id)

    await session.refresh(run)
    assert run.status == "success"
    assert run.rows == 7
    assert run.started_at is not None and run.finished_at is not None
    assert run.error is None
    # The load step ran against the resolved tenant scope + the pipeline's target.
    assert captured["table"] == "orders"
    assert captured["db"]  # a real per-tenant db, resolved from the registry


@pytest.mark.asyncio
async def test_failing_step_marks_error(session: AsyncSession, make_tenant: Any) -> None:
    tenant = await make_tenant("local")
    _pipeline, run = await _seed(session, tenant)

    async def boom(ctx: TenantContext, source: Any, secret: Any, target: str, spec: Any) -> Any:
        raise RuntimeError("source unreachable")

    await _executor(extract=boom).execute(session, run.id)

    await session.refresh(run)
    assert run.status == "error"
    assert "source unreachable" in (run.error or "")
    assert run.finished_at is not None
    assert run.rows is None


@pytest.mark.asyncio
async def test_missing_run_is_noop(session: AsyncSession, make_tenant: Any) -> None:
    await make_tenant("local")
    # Should not raise when the run id doesn't exist.
    await _executor().execute(session, uuid.uuid4())


@pytest.mark.asyncio
async def test_merge_disposition_passes_primary_key(
    session: AsyncSession, make_tenant: Any
) -> None:
    tenant = await make_tenant("local")
    _pipeline, run = await _seed(
        session,
        tenant,
        config={
            "object": "orders",
            "write_disposition": "merge",
            "primary_key": ["id"],
            "columns": [{"source_name": "id", "target_name": "id"}],
        },
    )
    captured: dict[str, Any] = {}

    def load(ctx: TenantContext, table: str, arrow: Any, plan: Any) -> int:
        captured["disposition"] = plan.disposition
        captured["primary_key"] = plan.primary_key
        return 3

    await _executor(load=load).execute(session, run.id)

    await session.refresh(run)
    assert run.status == "success"
    assert captured["disposition"] == "merge"
    assert captured["primary_key"] == ["id"]


@pytest.mark.asyncio
async def test_incremental_reads_and_advances_cdc_watermark(
    session: AsyncSession, make_tenant: Any
) -> None:
    import pyarrow as pa

    tenant = await make_tenant("local")
    pipeline, run = await _seed(
        session,
        tenant,
        config={
            "object": "orders",
            "write_disposition": "incremental",
            "cdc_column": "updated",
            "columns": [{"source_name": "updated", "target_name": "updated"}],
        },
    )
    pipeline.cursor = {"cdc": 100}  # prior high-water mark
    await session.flush()

    captured: dict[str, Any] = {}

    async def extract(ctx: TenantContext, source: Any, secret: Any, target: str, spec: Any) -> Any:
        captured["cdc_since"] = spec.cdc_since
        captured["cdc_column"] = spec.cdc_column
        # Two newer rows; max(updated)=140 becomes the next watermark.
        return pa.table({"updated": [120, 140]})

    def load(ctx: TenantContext, table: str, arrow: Any, plan: Any) -> int:
        return int(arrow.num_rows)

    await _executor(extract=extract, load=load).execute(session, run.id)

    await session.refresh(run)
    assert run.status == "success"
    # The prior mark was pushed into the extract, and the cursor advanced to the new max.
    assert captured["cdc_since"] == 100
    assert captured["cdc_column"] == "updated"
    assert pipeline.cursor == {"cdc": 140}


@pytest.mark.asyncio
async def test_scd2_is_rejected(session: AsyncSession, make_tenant: Any) -> None:
    tenant = await make_tenant("local")
    _pipeline, run = await _seed(
        session,
        tenant,
        config={"object": "orders", "scd_type": "scd2", "primary_key": ["id"]},
    )
    await _executor().execute(session, run.id)
    await session.refresh(run)
    assert run.status == "error"
    assert "SCD type 2" in (run.error or "")
