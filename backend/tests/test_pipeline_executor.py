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


async def _seed(session: AsyncSession, tenant: Any) -> tuple[Pipeline, PipelineRun]:
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
        config={"object": "orders", "write_disposition": "overwrite"},
        target_table="orders",
    )
    session.add(pipeline)
    await session.flush()
    run = PipelineRun(tenant_id=tenant.id, pipeline_id=pipeline.id, status="queued")
    session.add(run)
    await session.flush()
    return pipeline, run


def _executor(*, extract: Any = None, load: Any = None, register: Any = None) -> PipelineExecutor:
    async def _extract(ctx: TenantContext, source: Any, secret: Any, target: str) -> Any:
        return "arrow-sentinel"

    def _load(ctx: TenantContext, table: str, arrow: Any) -> int:
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

    def load(ctx: TenantContext, table: str, arrow: Any) -> int:
        captured["table"] = table
        captured["db"] = ctx.clickhouse_db
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

    async def boom(ctx: TenantContext, source: Any, secret: Any, target: str) -> Any:
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
