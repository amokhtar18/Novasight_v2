"""Saved-chart business logic: tenant-scoped CRUD over persisted ``ChartSpec``s.

Every query is scoped to ``ctx.tenant_id`` (tenancy-isolation invariant); a chart
owned by another tenant is indistinguishable from not-found (404). The spec is stored
as JSON (``mode="json"`` so embedded UUIDs serialise) and re-validated against
``ChartSpec`` on read, so a malformed stored spec fails loudly rather than rendering
garbage.
"""
from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.chart import Chart
from app.schemas.chart import ChartSpec
from app.schemas.saved_chart import ChartCreate, ChartRead, ChartUpdate
from app.tenancy.context import TenantContext


def chart_to_read(chart: Chart) -> ChartRead:
    """Map a ``Chart`` row to ``ChartRead``, re-validating the stored spec.

    Shared by the charts router and the dashboards service (tiles embed the chart),
    so a malformed stored spec fails loudly in exactly one place.
    """
    return ChartRead(
        id=chart.id,
        name=chart.name,
        spec=ChartSpec.model_validate(chart.spec),
        source_kind=chart.source_kind,
        source_ref=chart.source_ref,
        owner_id=chart.owner_id,
        created_at=chart.created_at,
        updated_at=chart.updated_at,
    )


class ChartService:
    """Create, list, and manage a tenant's saved charts."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def list_for_tenant(self, ctx: TenantContext) -> list[Chart]:
        result = await self._db.execute(
            select(Chart)
            .where(Chart.tenant_id == uuid.UUID(ctx.tenant_id))
            .order_by(Chart.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_for_tenant(self, ctx: TenantContext, chart_id: uuid.UUID) -> Chart:
        result = await self._db.execute(
            select(Chart).where(
                Chart.id == chart_id,
                Chart.tenant_id == uuid.UUID(ctx.tenant_id),
            )
        )
        chart = result.scalar_one_or_none()
        if chart is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chart not found")
        return chart

    async def create(
        self,
        ctx: TenantContext,
        data: ChartCreate,
        *,
        owner_id: uuid.UUID | None = None,
    ) -> Chart:
        chart = Chart(
            tenant_id=uuid.UUID(ctx.tenant_id),
            name=data.name,
            spec=data.spec.model_dump(mode="json"),
            source_kind=data.source_kind,
            source_ref=data.source_ref,
            owner_id=owner_id,
        )
        self._db.add(chart)
        await self._db.flush()
        await self._db.refresh(chart)
        return chart

    async def update(
        self, ctx: TenantContext, chart_id: uuid.UUID, data: ChartUpdate
    ) -> Chart:
        chart = await self.get_for_tenant(ctx, chart_id)
        if data.name is not None:
            chart.name = data.name
        if data.spec is not None:
            chart.spec = data.spec.model_dump(mode="json")
        if data.source_kind is not None:
            chart.source_kind = data.source_kind
        if data.source_ref is not None:
            chart.source_ref = data.source_ref
        await self._db.flush()
        await self._db.refresh(chart)
        return chart

    async def delete(self, ctx: TenantContext, chart_id: uuid.UUID) -> None:
        chart = await self.get_for_tenant(ctx, chart_id)
        await self._db.delete(chart)
        await self._db.flush()


def get_chart_service(
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> ChartService:
    """FastAPI dependency: assemble a ``ChartService`` from request scope."""
    return ChartService(db=db)
