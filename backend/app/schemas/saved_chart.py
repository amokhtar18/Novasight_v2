"""Request/response schemas for persisted charts (#9 / #10).

A saved chart is a named ``ChartSpec`` plus where its data comes from. The spec is
the *same* contract the renderer and the AI ``NL→chart`` path use, so manual, AI, and
saved charts are interchangeable. Charts are the unit dashboards compose.

Persisting the spec (not a data snapshot) means a chart re-runs its grounded query
when displayed, so it always reflects current data. The ``source_ref`` records which
governed model / dataset the spec reads, for listing and future re-grounding.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.schemas.chart import ChartSpec

# Where a saved chart reads its data: a governed semantic model or a dataset.
SourceKind = Literal["semantic", "dataset"]

# The model/dataset identifier the spec reads (Cube cube name or dataset id, as a
# string). Bounded + pattern-checked so it cannot smuggle arbitrary text.
SourceRef = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9_.\-]+$", min_length=1, max_length=64),
]


class ChartCreate(BaseModel):
    """Body for ``POST /charts``."""

    name: str = Field(..., min_length=1, max_length=255)
    spec: ChartSpec
    source_kind: SourceKind = "semantic"
    source_ref: SourceRef | None = None


class ChartUpdate(BaseModel):
    """Body for ``PATCH /charts/{id}`` — partial; omit a field to keep it."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    spec: ChartSpec | None = None
    source_kind: SourceKind | None = None
    source_ref: SourceRef | None = None


class ChartRead(BaseModel):
    """A saved chart as returned to clients."""

    id: uuid.UUID
    name: str
    spec: ChartSpec
    source_kind: str
    source_ref: str | None
    owner_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
