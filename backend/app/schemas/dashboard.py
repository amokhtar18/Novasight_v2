"""Request/response schemas for persisted dashboards (#10).

A dashboard is an ordered grid of tiles; each tile references a saved ``Chart`` with
its grid placement. Persisting server-side (replacing the old localStorage store)
makes dashboards shareable and durable across devices. Tiles store *no* data — they
embed the saved chart's ``spec`` and the frontend re-runs its grounded query when
displayed, so a dashboard always reflects current data.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.saved_chart import ChartRead


class DashboardCreate(BaseModel):
    """Body for ``POST /dashboards``."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)


class DashboardUpdate(BaseModel):
    """Body for ``PATCH /dashboards/{id}`` — partial."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)


class DashboardTileCreate(BaseModel):
    """Body for ``POST /dashboards/{id}/tiles`` — pin a saved chart."""

    chart_id: uuid.UUID
    title: str | None = Field(default=None, max_length=255)
    w: int | None = Field(default=None, ge=1, le=12)
    h: int | None = Field(default=None, ge=1, le=12)


class DashboardTileUpdate(BaseModel):
    """Body for ``PATCH /dashboards/{id}/tiles/{tile_id}`` — partial."""

    title: str | None = Field(default=None, max_length=255)
    position: int | None = Field(default=None, ge=0)
    x: int | None = Field(default=None, ge=0)
    y: int | None = Field(default=None, ge=0)
    w: int | None = Field(default=None, ge=1, le=12)
    h: int | None = Field(default=None, ge=1, le=12)


class TileLayout(BaseModel):
    """One tile's placement, used for bulk layout persistence (dnd-kit drag/resize)."""

    id: uuid.UUID
    position: int = Field(ge=0)
    x: int = Field(default=0, ge=0)
    y: int = Field(default=0, ge=0)
    w: int = Field(default=6, ge=1, le=12)
    h: int = Field(default=4, ge=1, le=12)


class DashboardLayoutUpdate(BaseModel):
    """Body for ``PUT /dashboards/{id}/layout`` — persist the whole grid at once."""

    tiles: list[TileLayout] = Field(default_factory=list)


class DashboardTileRead(BaseModel):
    """A placed tile, with its saved chart embedded so the grid renders in one round-trip."""

    id: uuid.UUID
    chart_id: uuid.UUID
    title: str | None
    position: int
    x: int
    y: int
    w: int
    h: int
    chart: ChartRead


class DashboardSummary(BaseModel):
    """A dashboard in the list view (no tiles, just a count)."""

    id: uuid.UUID
    name: str
    description: str | None
    owner_id: uuid.UUID | None
    tile_count: int
    created_at: datetime
    updated_at: datetime


class DashboardRead(BaseModel):
    """A dashboard with its ordered tiles (detail view)."""

    id: uuid.UUID
    name: str
    description: str | None
    owner_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    tiles: list[DashboardTileRead]
