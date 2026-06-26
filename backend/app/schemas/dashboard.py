"""Request/response schemas for persisted dashboards (#10).

A dashboard is an ordered grid of tiles; each tile references a saved ``Chart`` with
its grid placement. Persisting server-side (replacing the old localStorage store)
makes dashboards shareable and durable across devices. Tiles store *no* data — they
embed the saved chart's ``spec`` and the frontend re-runs its grounded query when
displayed, so a dashboard always reflects current data.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.saved_chart import ChartRead
from app.schemas.semantic import FilterOperator, RelativeDateRange, SemanticRef

# What a dashboard tile holds (#10): a pinned chart, or a decoration object.
# (Slice C removes the standalone "filter" slicer tile — native filters replace it.)
TileKind = Literal["chart", "text", "markdown", "image", "divider"]

# A native filter is one of three typed kinds (Slice C).
NativeFilterKind = Literal["value", "time", "numeric"]


class NumericRange(BaseModel):
    """A numeric filter's [min, max] bounds (either side optional)."""

    min: float | None = None
    max: float | None = None

    @model_validator(mode="after")
    def _min_le_max(self) -> NumericRange:
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("numeric_range min must not be greater than max")
        return self


class FilterScope(BaseModel):
    """Which tiles a native filter targets. ``auto`` = every cube-compatible tile."""

    mode: Literal["auto", "tiles"] = "auto"
    tile_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)


class NativeFilter(BaseModel):
    """A configured dashboard filter control. Persisted with its *default* selection;
    the live selection is client state seeded from the default."""

    id: str = Field(..., min_length=1, max_length=64)
    kind: NativeFilterKind
    member: SemanticRef
    label: str | None = Field(default=None, max_length=128)
    # value-filter fields
    operator: FilterOperator = "equals"
    default_values: list[str] = Field(default_factory=list, max_length=100)
    # time-filter field (reuses Slice A's relative token | absolute [from, to] model)
    date_range: RelativeDateRange | list[str] | None = None
    # numeric-filter field
    numeric_range: NumericRange | None = None
    scope: FilterScope = Field(default_factory=FilterScope)
    parent_id: str | None = Field(default=None, max_length=64)
    required: bool = False

    @model_validator(mode="after")
    def _validate(self) -> NativeFilter:
        # A value filter only uses set-membership/substring operators.
        if self.kind == "value" and self.operator in {"set", "notSet", "gt", "gte", "lt", "lte"}:
            raise ValueError("a value filter uses equals/notEquals/contains/notContains")
        if isinstance(self.date_range, list):
            if len(self.date_range) != 2:
                raise ValueError("an absolute date_range must be exactly two ISO dates")
            try:
                start, end = (date.fromisoformat(d) for d in self.date_range)
            except ValueError as exc:
                raise ValueError("date_range entries must be ISO dates (YYYY-MM-DD)") from exc
            if start > end:
                raise ValueError("date_range start must not be after end")
        if self.parent_id is not None and self.parent_id == self.id:
            raise ValueError("a filter cannot be its own parent")
        return self


class DashboardCreate(BaseModel):
    """Body for ``POST /dashboards``."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)


class DashboardUpdate(BaseModel):
    """Body for ``PATCH /dashboards/{id}`` — partial.

    ``native_filters`` (when provided) replaces the dashboard's native filters. Members
    are shape-validated here and re-validated against the governed allow-list when a
    tile runs — persisting a filter never widens data access.
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    native_filters: list[NativeFilter] | None = Field(default=None, max_length=20)

    @model_validator(mode="after")
    def _validate_filters(self) -> DashboardUpdate:
        if self.native_filters is None:
            return self
        by_id = {f.id: f for f in self.native_filters}
        if len(by_id) != len(self.native_filters):
            raise ValueError("native_filters ids must be unique")
        for f in self.native_filters:
            if f.parent_id is None:
                continue
            parent = by_id.get(f.parent_id)
            if parent is None:
                raise ValueError(f"filter {f.id!r} references unknown parent {f.parent_id!r}")
            if parent.kind != "value":
                raise ValueError("a filter parent must be a value filter")
            seen = {f.id}
            cur: NativeFilter | None = parent
            while cur is not None:
                if cur.id in seen:
                    raise ValueError("native_filters contain a parent cycle")
                seen.add(cur.id)
                cur = by_id.get(cur.parent_id) if cur.parent_id else None
        return self


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
    native_filters: list[NativeFilter] = Field(default_factory=list)
    tiles: list[DashboardTileRead]
