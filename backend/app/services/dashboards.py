"""Dashboard business logic: tenant-scoped dashboards + tiles (replaces localStorage).

Every query is scoped to ``ctx.tenant_id`` (tenancy-isolation invariant); a dashboard
or tile owned by another tenant is indistinguishable from not-found (404). A tile may
only reference a chart owned by the same tenant — the chart ownership is re-checked
server-side on every pin, so a tile can never point across tenants.

Tiles store no data: each embeds its saved chart's spec and the frontend re-runs the
chart's grounded query when rendering, so a dashboard always reflects current data.
"""
from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.db import get_db
from app.models.chart import Chart
from app.models.dashboard import Dashboard, DashboardTile
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
from app.services.charts import chart_to_read
from app.tenancy.context import TenantContext

# Default tile placement on the 12-column grid when the client omits a size.
_DEFAULT_W = 6
_DEFAULT_H = 4


class DashboardService:
    """Manage a tenant's dashboards and their tiles."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Dashboards
    # ------------------------------------------------------------------

    async def list_for_tenant(self, ctx: TenantContext) -> list[DashboardSummary]:
        result = await self._db.execute(
            select(Dashboard)
            .where(Dashboard.tenant_id == uuid.UUID(ctx.tenant_id))
            .options(selectinload(Dashboard.tiles))
            .order_by(Dashboard.created_at.desc())
        )
        return [
            DashboardSummary(
                id=d.id,
                name=d.name,
                description=d.description,
                owner_id=d.owner_id,
                tile_count=len(d.tiles),
                created_at=d.created_at,
                updated_at=d.updated_at,
            )
            for d in result.scalars().all()
        ]

    async def get_read(self, ctx: TenantContext, dashboard_id: uuid.UUID) -> DashboardRead:
        """Load a dashboard with its ordered tiles, each embedding its chart."""
        dashboard = await self._get(ctx, dashboard_id)
        charts = await self._charts_by_id(
            ctx, [t.chart_id for t in dashboard.tiles]
        )
        return self._to_read(dashboard, charts)

    async def create(
        self,
        ctx: TenantContext,
        data: DashboardCreate,
        *,
        owner_id: uuid.UUID | None = None,
    ) -> DashboardRead:
        dashboard = Dashboard(
            tenant_id=uuid.UUID(ctx.tenant_id),
            name=data.name,
            description=data.description,
            owner_id=owner_id,
        )
        self._db.add(dashboard)
        await self._db.flush()
        await self._db.refresh(dashboard)
        # A brand-new dashboard has no tiles; build the read directly rather than
        # touching the (unloaded) lazy ``tiles`` relationship in async context.
        return DashboardRead(
            id=dashboard.id,
            name=dashboard.name,
            description=dashboard.description,
            owner_id=dashboard.owner_id,
            created_at=dashboard.created_at,
            updated_at=dashboard.updated_at,
            tiles=[],
        )

    async def update(
        self, ctx: TenantContext, dashboard_id: uuid.UUID, data: DashboardUpdate
    ) -> DashboardRead:
        dashboard = await self._get(ctx, dashboard_id)
        if data.name is not None:
            dashboard.name = data.name
        if data.description is not None:
            dashboard.description = data.description
        await self._db.flush()
        charts = await self._charts_by_id(ctx, [t.chart_id for t in dashboard.tiles])
        return self._to_read(dashboard, charts)

    async def delete(self, ctx: TenantContext, dashboard_id: uuid.UUID) -> None:
        dashboard = await self._get(ctx, dashboard_id)
        await self._db.delete(dashboard)
        await self._db.flush()

    # ------------------------------------------------------------------
    # Tiles
    # ------------------------------------------------------------------

    async def add_tile(
        self, ctx: TenantContext, dashboard_id: uuid.UUID, data: DashboardTileCreate
    ) -> DashboardTileRead:
        dashboard = await self._get(ctx, dashboard_id)
        chart = await self._get_chart(ctx, data.chart_id)

        next_position = (
            max((t.position for t in dashboard.tiles), default=-1) + 1
        )
        tile = DashboardTile(
            tenant_id=uuid.UUID(ctx.tenant_id),
            dashboard_id=dashboard.id,
            chart_id=chart.id,
            title=data.title,
            position=next_position,
            w=data.w if data.w is not None else _DEFAULT_W,
            h=data.h if data.h is not None else _DEFAULT_H,
        )
        self._db.add(tile)
        await self._db.flush()
        await self._db.refresh(tile)
        return self._tile_to_read(tile, chart)

    async def update_tile(
        self,
        ctx: TenantContext,
        dashboard_id: uuid.UUID,
        tile_id: uuid.UUID,
        data: DashboardTileUpdate,
    ) -> DashboardTileRead:
        tile = await self._get_tile(ctx, dashboard_id, tile_id)
        if data.title is not None:
            tile.title = data.title
        if data.position is not None:
            tile.position = data.position
        if data.x is not None:
            tile.x = data.x
        if data.y is not None:
            tile.y = data.y
        if data.w is not None:
            tile.w = data.w
        if data.h is not None:
            tile.h = data.h
        await self._db.flush()
        chart = await self._get_chart(ctx, tile.chart_id)
        return self._tile_to_read(tile, chart)

    async def delete_tile(
        self, ctx: TenantContext, dashboard_id: uuid.UUID, tile_id: uuid.UUID
    ) -> None:
        tile = await self._get_tile(ctx, dashboard_id, tile_id)
        await self._db.delete(tile)
        await self._db.flush()

    async def set_layout(
        self, ctx: TenantContext, dashboard_id: uuid.UUID, data: DashboardLayoutUpdate
    ) -> DashboardRead:
        """Persist the whole grid at once (drag-reorder + resize)."""
        dashboard = await self._get(ctx, dashboard_id)
        by_id = {t.id: t for t in dashboard.tiles}
        for layout in data.tiles:
            tile = by_id.get(layout.id)
            if tile is None:
                # Ignore ids that aren't tiles of this dashboard (stale client state).
                continue
            tile.position = layout.position
            tile.x = layout.x
            tile.y = layout.y
            tile.w = layout.w
            tile.h = layout.h
        await self._db.flush()
        charts = await self._charts_by_id(ctx, [t.chart_id for t in dashboard.tiles])
        return self._to_read(dashboard, charts)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _get(self, ctx: TenantContext, dashboard_id: uuid.UUID) -> Dashboard:
        result = await self._db.execute(
            select(Dashboard)
            .where(
                Dashboard.id == dashboard_id,
                Dashboard.tenant_id == uuid.UUID(ctx.tenant_id),
            )
            .options(selectinload(Dashboard.tiles))
        )
        dashboard = result.scalar_one_or_none()
        if dashboard is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Dashboard not found"
            )
        return dashboard

    async def _get_tile(
        self, ctx: TenantContext, dashboard_id: uuid.UUID, tile_id: uuid.UUID
    ) -> DashboardTile:
        result = await self._db.execute(
            select(DashboardTile).where(
                DashboardTile.id == tile_id,
                DashboardTile.dashboard_id == dashboard_id,
                DashboardTile.tenant_id == uuid.UUID(ctx.tenant_id),
            )
        )
        tile = result.scalar_one_or_none()
        if tile is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tile not found")
        return tile

    async def _get_chart(self, ctx: TenantContext, chart_id: uuid.UUID) -> Chart:
        result = await self._db.execute(
            select(Chart).where(
                Chart.id == chart_id,
                Chart.tenant_id == uuid.UUID(ctx.tenant_id),
            )
        )
        chart = result.scalar_one_or_none()
        if chart is None:
            # A chart from another tenant (or non-existent) is indistinguishable.
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chart not found")
        return chart

    async def _charts_by_id(
        self, ctx: TenantContext, chart_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, Chart]:
        if not chart_ids:
            return {}
        result = await self._db.execute(
            select(Chart).where(
                Chart.id.in_(set(chart_ids)),
                Chart.tenant_id == uuid.UUID(ctx.tenant_id),
            )
        )
        return {c.id: c for c in result.scalars().all()}

    def _to_read(
        self, dashboard: Dashboard, charts: dict[uuid.UUID, Chart]
    ) -> DashboardRead:
        tiles = [
            self._tile_to_read(t, charts[t.chart_id])
            for t in sorted(dashboard.tiles, key=lambda t: t.position)
            if t.chart_id in charts
        ]
        return DashboardRead(
            id=dashboard.id,
            name=dashboard.name,
            description=dashboard.description,
            owner_id=dashboard.owner_id,
            created_at=dashboard.created_at,
            updated_at=dashboard.updated_at,
            tiles=tiles,
        )

    @staticmethod
    def _tile_to_read(tile: DashboardTile, chart: Chart) -> DashboardTileRead:
        return DashboardTileRead(
            id=tile.id,
            chart_id=tile.chart_id,
            title=tile.title,
            position=tile.position,
            x=tile.x,
            y=tile.y,
            w=tile.w,
            h=tile.h,
            chart=chart_to_read(chart),
        )


def get_dashboard_service(
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> DashboardService:
    """FastAPI dependency: assemble a ``DashboardService`` from request scope."""
    return DashboardService(db=db)
