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
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.saved_chart import ChartRead
from app.schemas.semantic import SemanticFilter

# What a dashboard tile holds (#10): a pinned chart, or a decoration object.
TileKind = Literal["chart", "text", "markdown", "image", "divider", "filter"]


class DashboardCreate(BaseModel):
    """Body for ``POST /dashboards``."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)


class DashboardUpdate(BaseModel):
    """Body for ``PATCH /dashboards/{id}`` — partial.

    ``filters`` (when provided) replaces the dashboard's view-time filters. Each
    member is shape-validated here and re-validated against the governed allow-list
    by the semantic query path when a tile runs — persisting a filter never widens
    data access.
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    filters: list[SemanticFilter] | None = Field(default=None, max_length=20)


class DashboardTileCreate(BaseModel):
    """Body for ``POST /dashboards/{id}/tiles`` — pin a chart or add an object (#10).

    A ``chart`` tile requires ``chart_id``; every other ``kind`` carries its payload in
    ``content`` (e.g. ``{"text": "..."}``, ``{"url": "..."}``, ``{"member": "..."}``) and
    must not set ``chart_id``.
    """

    kind: TileKind = "chart"
    chart_id: uuid.UUID | None = None
    content: dict[str, Any] | None = None
    title: str | None = Field(default=None, max_length=255)
    w: int | None = Field(default=None, ge=1, le=12)
    h: int | None = Field(default=None, ge=1, le=12)

    @model_validator(mode="after")
    def _check_kind(self) -> DashboardTileCreate:
        if self.kind == "chart" and self.chart_id is None:
            raise ValueError("a chart tile requires chart_id")
        if self.kind != "chart" and self.chart_id is not None:
            raise ValueError(f"a {self.kind} tile must not set chart_id")
        return self


class DashboardTileUpdate(BaseModel):
    """Body for ``PATCH /dashboards/{id}/tiles/{tile_id}`` — partial."""

    title: str | None = Field(default=None, max_length=255)
    # Replace a decoration tile's payload (e.g. edit text/markdown/image).
    content: dict[str, Any] | None = None
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
    """A placed tile. Chart tiles embed their saved chart so the grid renders in one
    round-trip; decoration tiles (#10) carry their ``content`` and a null ``chart``."""

    id: uuid.UUID
    kind: str
    chart_id: uuid.UUID | None
    content: dict[str, Any] | None
    title: str | None
    position: int
    x: int
    y: int
    w: int
    h: int
    chart: ChartRead | None


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
    filters: list[SemanticFilter] = Field(default_factory=list)
    tiles: list[DashboardTileRead]
