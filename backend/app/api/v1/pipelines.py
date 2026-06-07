"""ETL pipeline endpoints — CRUD, run history, and run-now (#3).

Reads (list/get/runs) require only a tenant context. Mutations and run-now require
the tenant **superuser** role, since they configure and trigger data-engineering
plumbing (reaching external sources, writing the lake + ClickHouse). The tenant is
resolved from the JWT — never a body/path value.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response, status

from app.core.security import Principal, require_tenant_superuser
from app.models.pipeline import Pipeline, PipelineRun
from app.schemas.pipeline import (
    PipelineConfig,
    PipelineCreate,
    PipelineRead,
    PipelineRunRead,
    PipelineUpdate,
)
from app.services.pipelines import PipelineService, get_pipeline_service
from app.tenancy.context import TenantContext, get_tenant_context

router = APIRouter(prefix="/pipelines", tags=["pipelines"])


def _to_read(p: Pipeline) -> PipelineRead:
    return PipelineRead(
        id=p.id,
        name=p.name,
        source_connection_id=p.source_connection_id,
        config=PipelineConfig.model_validate(p.config),
        target_table=p.target_table,
        enabled=p.enabled,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


def _run_to_read(r: PipelineRun) -> PipelineRunRead:
    return PipelineRunRead(
        id=r.id,
        pipeline_id=r.pipeline_id,
        status=r.status,
        dagster_run_id=r.dagster_run_id,
        rows=r.rows,
        started_at=r.started_at,
        finished_at=r.finished_at,
        error=r.error,
        created_at=r.created_at,
    )


@router.get("", response_model=list[PipelineRead])
async def list_pipelines(
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    svc: PipelineService = Depends(get_pipeline_service),  # noqa: B008
) -> list[PipelineRead]:
    """List the tenant's pipelines."""
    return [_to_read(p) for p in await svc.list_for_tenant(ctx)]


@router.get("/{pipeline_id}", response_model=PipelineRead)
async def get_pipeline(
    pipeline_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    svc: PipelineService = Depends(get_pipeline_service),  # noqa: B008
) -> PipelineRead:
    """Fetch one pipeline (404 if not in the caller's tenant)."""
    return _to_read(await svc.get_for_tenant(ctx, pipeline_id))


@router.post("", response_model=PipelineRead, status_code=status.HTTP_201_CREATED)
async def create_pipeline(
    payload: PipelineCreate,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    _: Principal = Depends(require_tenant_superuser),  # noqa: B008
    svc: PipelineService = Depends(get_pipeline_service),  # noqa: B008
) -> PipelineRead:
    """Create a pipeline (source must belong to the tenant)."""
    return _to_read(await svc.create(ctx, payload))


@router.patch("/{pipeline_id}", response_model=PipelineRead)
async def update_pipeline(
    pipeline_id: uuid.UUID,
    payload: PipelineUpdate,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    _: Principal = Depends(require_tenant_superuser),  # noqa: B008
    svc: PipelineService = Depends(get_pipeline_service),  # noqa: B008
) -> PipelineRead:
    """Update a pipeline (partial)."""
    return _to_read(await svc.update(ctx, pipeline_id, payload))


@router.delete("/{pipeline_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pipeline(
    pipeline_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    _: Principal = Depends(require_tenant_superuser),  # noqa: B008
    svc: PipelineService = Depends(get_pipeline_service),  # noqa: B008
) -> Response:
    """Delete a pipeline and its run history."""
    await svc.delete(ctx, pipeline_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{pipeline_id}/runs", response_model=list[PipelineRunRead])
async def list_runs(
    pipeline_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    svc: PipelineService = Depends(get_pipeline_service),  # noqa: B008
) -> list[PipelineRunRead]:
    """List a pipeline's run history, newest first."""
    return [_run_to_read(r) for r in await svc.list_runs(ctx, pipeline_id)]


@router.post(
    "/{pipeline_id}/run",
    response_model=PipelineRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_pipeline_now(
    pipeline_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    _: Principal = Depends(require_tenant_superuser),  # noqa: B008
    svc: PipelineService = Depends(get_pipeline_service),  # noqa: B008
) -> PipelineRunRead:
    """Queue a run now and return it (executes off the request path in a worker)."""
    return _run_to_read(await svc.run_now(ctx, pipeline_id))
