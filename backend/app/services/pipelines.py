"""ETL pipeline business logic: tenant-scoped CRUD + run-now enqueue (#3).

A pipeline binds a saved ``SourceConnection`` to a selection and a target Iceberg
table. ``run_now`` records a queued ``PipelineRun`` and enqueues the worker actor that
executes it (extract → Iceberg → ClickHouse). Enqueue is injectable so the API layer
imports without a broker and tests verify the enqueue without one.

Every query is scoped to ``ctx.tenant_id``; a pipeline (or its source) from another
tenant is indistinguishable from not-found (404).
"""
from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.pipeline import Pipeline, PipelineRun
from app.models.source_connection import SourceConnection
from app.schemas.pipeline import PipelineCreate, PipelineUpdate
from app.tenancy.context import TenantContext

EnqueueFn = Callable[[str], None]


class PipelineService:
    """Manage a tenant's ETL pipelines and launch runs."""

    def __init__(self, db: AsyncSession, enqueue: EnqueueFn | None = None) -> None:
        self._db = db
        # When None, run_now lazily imports the actor (which needs a broker). Tests
        # inject a fake to verify enqueue without configuring one.
        self._enqueue = enqueue

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def list_for_tenant(self, ctx: TenantContext) -> list[Pipeline]:
        result = await self._db.execute(
            select(Pipeline)
            .where(Pipeline.tenant_id == uuid.UUID(ctx.tenant_id))
            .order_by(Pipeline.name.asc())
        )
        return list(result.scalars().all())

    async def get_for_tenant(self, ctx: TenantContext, pipeline_id: uuid.UUID) -> Pipeline:
        result = await self._db.execute(
            select(Pipeline).where(
                Pipeline.id == pipeline_id,
                Pipeline.tenant_id == uuid.UUID(ctx.tenant_id),
            )
        )
        pipeline = result.scalar_one_or_none()
        if pipeline is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline not found")
        return pipeline

    async def create(self, ctx: TenantContext, data: PipelineCreate) -> Pipeline:
        # The source connection must belong to the same tenant (no cross-tenant binding).
        await self._require_source(ctx, data.source_connection_id)
        pipeline = Pipeline(
            tenant_id=uuid.UUID(ctx.tenant_id),
            source_connection_id=data.source_connection_id,
            name=data.name,
            config=data.config.model_dump(),
            target_table=data.target_table,
            enabled=data.enabled,
        )
        self._db.add(pipeline)
        await self._db.flush()
        await self._db.refresh(pipeline)
        return pipeline

    async def update(
        self, ctx: TenantContext, pipeline_id: uuid.UUID, data: PipelineUpdate
    ) -> Pipeline:
        pipeline = await self.get_for_tenant(ctx, pipeline_id)
        if data.name is not None:
            pipeline.name = data.name
        if data.config is not None:
            pipeline.config = data.config.model_dump()
        if data.target_table is not None:
            pipeline.target_table = data.target_table
        if data.enabled is not None:
            pipeline.enabled = data.enabled
        await self._db.flush()
        await self._db.refresh(pipeline)
        return pipeline

    async def delete(self, ctx: TenantContext, pipeline_id: uuid.UUID) -> None:
        pipeline = await self.get_for_tenant(ctx, pipeline_id)
        await self._db.delete(pipeline)
        await self._db.flush()

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------

    async def list_runs(self, ctx: TenantContext, pipeline_id: uuid.UUID) -> list[PipelineRun]:
        # Verify ownership first (404 if not this tenant's pipeline).
        await self.get_for_tenant(ctx, pipeline_id)
        result = await self._db.execute(
            select(PipelineRun)
            .where(
                PipelineRun.pipeline_id == pipeline_id,
                PipelineRun.tenant_id == uuid.UUID(ctx.tenant_id),
            )
            .order_by(PipelineRun.created_at.desc())
        )
        return list(result.scalars().all())

    async def run_now(self, ctx: TenantContext, pipeline_id: uuid.UUID) -> PipelineRun:
        """Record a queued run and enqueue its execution (off the request path)."""
        pipeline = await self.get_for_tenant(ctx, pipeline_id)
        if not pipeline.enabled:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Pipeline is disabled"
            )
        run = PipelineRun(
            tenant_id=uuid.UUID(ctx.tenant_id),
            pipeline_id=pipeline.id,
            status="queued",
        )
        self._db.add(run)
        await self._db.flush()
        await self._db.refresh(run)
        self._enqueue_run(str(run.id))
        return run

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _require_source(self, ctx: TenantContext, source_id: uuid.UUID) -> None:
        result = await self._db.execute(
            select(SourceConnection.id).where(
                SourceConnection.id == source_id,
                SourceConnection.tenant_id == uuid.UUID(ctx.tenant_id),
            )
        )
        if result.first() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Source connection not found"
            )

    def _enqueue_run(self, run_id: str) -> None:
        if self._enqueue is not None:
            self._enqueue(run_id)
            return
        # Lazy import: the actor module binds to the global broker at import time, so
        # the request path never imports it until an actual enqueue happens.
        from app.ingestion.actors import run_pipeline

        run_pipeline.send(run_id)


def get_pipeline_service(
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> PipelineService:
    """FastAPI dependency: assemble a ``PipelineService`` from request scope."""
    return PipelineService(db=db)
