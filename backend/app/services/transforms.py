"""Run dbt model builds via Dagster — the app-facing half of the dbt run path (#7).

The dbt-model wizard (``DbtModelService``) defines models and writes the tenant's dbt
project subtree; this service *runs* one. It resolves the model (tenant-scoped),
find-or-creates the tenant's ``TransformJob`` registry row for that model's selector,
and launches the generic Dagster ``transform_job`` for it. Dagster's ``run_transform``
op reads that row (``registry.load_transform``) and shells out to ``dbt build --select``.

Mirrors the pipeline run-now path, but the executor is Dagster (dbt runs in the
orchestration image, not the backend). Tenancy (golden rule 2): the model is scoped to
``ctx.tenant_id``; the run carries the tenant **slug** (from the verified principal,
never the client body) so the generic job materialises the right tenant's project.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.dbt_model import DbtModel
from app.models.transform_job import TransformJob
from app.orchestration.dagster_client import DagsterClient, get_dagster_client
from app.orchestration.run_config import TRANSFORM_JOB, transform_run_config
from app.tenancy.context import TenantContext


@dataclass(frozen=True)
class TransformLaunch:
    """The outcome of launching a dbt build: the registry row + the Dagster run id."""

    transform_job_id: uuid.UUID
    selection: str
    dagster_run_id: str


class TransformService:
    """Launch dbt builds for a tenant's models via the Dagster control plane."""

    def __init__(self, db: AsyncSession, dagster: DagsterClient) -> None:
        self._db = db
        self._dagster = dagster

    async def run_model(
        self, ctx: TenantContext, model_id: uuid.UUID, tenant_slug: str
    ) -> TransformLaunch:
        """Build one dbt model now: resolve it, ensure its transform job, launch Dagster."""
        model = await self._get_enabled_model(ctx, model_id)
        # A model's name is its dbt model name, so it is also the dbt selector.
        job = await self._ensure_transform_job(ctx, selection=model.name)
        run_id = await self._dagster.launch_run(
            job_name=TRANSFORM_JOB,
            run_config=transform_run_config(job.id, tenant_slug),
        )
        return TransformLaunch(
            transform_job_id=job.id, selection=model.name, dagster_run_id=run_id
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _get_enabled_model(self, ctx: TenantContext, model_id: uuid.UUID) -> DbtModel:
        result = await self._db.execute(
            select(DbtModel).where(
                DbtModel.id == model_id,
                DbtModel.tenant_id == uuid.UUID(ctx.tenant_id),
            )
        )
        model = result.scalar_one_or_none()
        if model is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="dbt model not found")
        if not model.enabled:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="dbt model is disabled"
            )
        return model

    async def _ensure_transform_job(
        self, ctx: TenantContext, *, selection: str
    ) -> TransformJob:
        """Find (or create) the tenant's transform job for ``selection``.

        One row per (tenant, selection) so repeated runs of a model reuse it rather than
        accumulating registry rows. Flushed (not committed) here — same as pipeline
        run-now: the request commits before Dagster's op, which starts with launch
        latency, reads the row.
        """
        existing = await self._db.execute(
            select(TransformJob).where(
                TransformJob.tenant_id == uuid.UUID(ctx.tenant_id),
                TransformJob.selection == selection,
            )
        )
        job = existing.scalar_one_or_none()
        if job is not None:
            return job
        job = TransformJob(
            tenant_id=uuid.UUID(ctx.tenant_id), name=selection, selection=selection
        )
        self._db.add(job)
        await self._db.flush()
        await self._db.refresh(job)
        return job


def get_transform_service(
    db: AsyncSession = Depends(get_db),  # noqa: B008
    dagster: DagsterClient = Depends(get_dagster_client),  # noqa: B008
) -> TransformService:
    """FastAPI dependency: assemble a ``TransformService`` from request scope."""
    return TransformService(db=db, dagster=dagster)
