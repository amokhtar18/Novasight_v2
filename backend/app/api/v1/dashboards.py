"""Dashboard endpoints — tenant-scoped CRUD over persisted dashboards + tiles (#10).

Replaces the old client-side localStorage store: dashboards now survive across
devices and are shareable within a tenant. A dashboard is an ordered grid of tiles,
each pinning a saved ``Chart``. Managing dashboards is a normal BI action, so reads
and writes require only a tenant context. The tenant is resolved from the JWT — never
a body/path value.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response, status

from app.schemas.dashboard import (
    DashboardCreate,
    DashboardLayoutUpdate,
    DashboardRead,
    DashboardSummary,
    DashboardTileCreate,
    DashboardTileRead,
    DashboardTileUpdate,
    DashboardUpdate,
)
from app.services.dashboards import DashboardService, get_dashboard_service
from app.tenancy.context import TenantContext, get_tenant_context

router = APIRouter(prefix="/dashboards", tags=["dashboards"])


@router.get("", response_model=list[DashboardSummary])
async def list_dashboards(
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    svc: DashboardService = Depends(get_dashboard_service),  # noqa: B008
) -> list[DashboardSummary]:
    """List the tenant's dashboards, newest first."""
    return await svc.list_for_tenant(ctx)


@router.post("", response_model=DashboardRead, status_code=status.HTTP_201_CREATED)
async def create_dashboard(
    payload: DashboardCreate,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    svc: DashboardService = Depends(get_dashboard_service),  # noqa: B008
) -> DashboardRead:
    """Create an empty dashboard."""
    return await svc.create(ctx, payload)


@router.get("/{dashboard_id}", response_model=DashboardRead)
async def get_dashboard(
    dashboard_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    svc: DashboardService = Depends(get_dashboard_service),  # noqa: B008
) -> DashboardRead:
    """Fetch one dashboard with its ordered tiles (each embeds its chart)."""
    return await svc.get_read(ctx, dashboard_id)


@router.patch("/{dashboard_id}", response_model=DashboardRead)
async def update_dashboard(
    dashboard_id: uuid.UUID,
    payload: DashboardUpdate,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    svc: DashboardService = Depends(get_dashboard_service),  # noqa: B008
) -> DashboardRead:
    """Rename / re-describe a dashboard."""
    return await svc.update(ctx, dashboard_id, payload)


@router.delete("/{dashboard_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dashboard(
    dashboard_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    svc: DashboardService = Depends(get_dashboard_service),  # noqa: B008
) -> Response:
    """Delete a dashboard and its tiles."""
    await svc.delete(ctx, dashboard_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/{dashboard_id}/layout", response_model=DashboardRead)
async def set_layout(
    dashboard_id: uuid.UUID,
    payload: DashboardLayoutUpdate,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    svc: DashboardService = Depends(get_dashboard_service),  # noqa: B008
) -> DashboardRead:
    """Persist the whole grid (tile order + sizes) after a drag/resize."""
    return await svc.set_layout(ctx, dashboard_id, payload)


@router.post(
    "/{dashboard_id}/tiles",
    response_model=DashboardTileRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_tile(
    dashboard_id: uuid.UUID,
    payload: DashboardTileCreate,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    svc: DashboardService = Depends(get_dashboard_service),  # noqa: B008
) -> DashboardTileRead:
    """Pin a saved chart onto the dashboard (404 if the chart isn't in the tenant)."""
    return await svc.add_tile(ctx, dashboard_id, payload)


@router.patch("/{dashboard_id}/tiles/{tile_id}", response_model=DashboardTileRead)
async def update_tile(
    dashboard_id: uuid.UUID,
    tile_id: uuid.UUID,
    payload: DashboardTileUpdate,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    svc: DashboardService = Depends(get_dashboard_service),  # noqa: B008
) -> DashboardTileRead:
    """Update one tile's title / placement."""
    return await svc.update_tile(ctx, dashboard_id, tile_id, payload)


@router.delete(
    "/{dashboard_id}/tiles/{tile_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_tile(
    dashboard_id: uuid.UUID,
    tile_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    svc: DashboardService = Depends(get_dashboard_service),  # noqa: B008
) -> Response:
    """Remove a tile from the dashboard."""
    await svc.delete_tile(ctx, dashboard_id, tile_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
