"""Saved-chart endpoints — tenant-scoped CRUD over persisted charts (#9 / #10).

A chart is a named ``ChartSpec`` the user built (manually on a semantic model, or via
the AI path) and chose to keep. Saving is a normal BI action, so reads and writes
require only a tenant context — any authenticated tenant user may manage their
tenant's charts. The tenant is resolved from the JWT, never a body/path value.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response, status

from app.models.chart import Chart
from app.schemas.chart import ChartSpec
from app.schemas.saved_chart import ChartCreate, ChartRead, ChartUpdate
from app.services.charts import ChartService, get_chart_service
from app.tenancy.context import TenantContext, get_tenant_context

router = APIRouter(prefix="/charts", tags=["charts"])


def _to_read(chart: Chart) -> ChartRead:
    return ChartRead(
        id=chart.id,
        name=chart.name,
        # Re-validate the stored spec so a malformed row fails loudly, not silently.
        spec=ChartSpec.model_validate(chart.spec),
        source_kind=chart.source_kind,
        source_ref=chart.source_ref,
        owner_id=chart.owner_id,
        created_at=chart.created_at,
        updated_at=chart.updated_at,
    )


@router.get("", response_model=list[ChartRead])
async def list_charts(
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    svc: ChartService = Depends(get_chart_service),  # noqa: B008
) -> list[ChartRead]:
    """List the tenant's saved charts, newest first."""
    return [_to_read(c) for c in await svc.list_for_tenant(ctx)]


@router.get("/{chart_id}", response_model=ChartRead)
async def get_chart(
    chart_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    svc: ChartService = Depends(get_chart_service),  # noqa: B008
) -> ChartRead:
    """Fetch one saved chart (404 if not in the caller's tenant)."""
    return _to_read(await svc.get_for_tenant(ctx, chart_id))


@router.post("", response_model=ChartRead, status_code=status.HTTP_201_CREATED)
async def create_chart(
    payload: ChartCreate,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    svc: ChartService = Depends(get_chart_service),  # noqa: B008
) -> ChartRead:
    """Save a new chart for the tenant."""
    return _to_read(await svc.create(ctx, payload))


@router.patch("/{chart_id}", response_model=ChartRead)
async def update_chart(
    chart_id: uuid.UUID,
    payload: ChartUpdate,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    svc: ChartService = Depends(get_chart_service),  # noqa: B008
) -> ChartRead:
    """Update a saved chart (partial)."""
    return _to_read(await svc.update(ctx, chart_id, payload))


@router.delete("/{chart_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chart(
    chart_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    svc: ChartService = Depends(get_chart_service),  # noqa: B008
) -> Response:
    """Delete a saved chart."""
    await svc.delete(ctx, chart_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
