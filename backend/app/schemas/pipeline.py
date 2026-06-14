"""Schemas for ETL pipeline definitions and their runs (#3).

A pipeline binds a saved ``SourceConnection`` to a selection (which object/table to
read) and a target Iceberg table in the tenant's namespace. ``run-now`` enqueues an
execution; ``PipelineRunRead`` exposes the run history (status, rows, timings, error).

The target table is a strict identifier (it names an Iceberg/ClickHouse table); the
selected ``object`` is a bounded string (DB table name or file key) the connector
validates. Tenant scope is never carried here — it's resolved server-side.
"""
from __future__ import annotations

import datetime
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

# Iceberg/ClickHouse table identifier (target landing table).
Identifier = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", min_length=1, max_length=128),
]

# Write disposition — only full overwrite for the slice (idempotent re-runs);
# incremental/append are a later (Phase 2) concern.
WriteDisposition = Literal["overwrite"]


class PipelineConfig(BaseModel):
    """Selection + load options for one pipeline."""

    # The source object to extract: a DB table name, or a file key/path for filesystem.
    object: str = Field(..., min_length=1, max_length=512)
    write_disposition: WriteDisposition = "overwrite"


class PipelineCreate(BaseModel):
    """Body for ``POST /pipelines``."""

    name: str = Field(..., min_length=1, max_length=255)
    source_connection_id: uuid.UUID
    config: PipelineConfig
    target_table: Identifier
    enabled: bool = True


class PipelineUpdate(BaseModel):
    """Body for ``PATCH /pipelines/{id}`` — partial."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    config: PipelineConfig | None = None
    target_table: Identifier | None = None
    enabled: bool | None = None


class PipelineRead(BaseModel):
    """A pipeline definition as returned to clients."""

    id: uuid.UUID
    name: str
    source_connection_id: uuid.UUID
    config: PipelineConfig
    target_table: str
    enabled: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime


class PipelineRunRead(BaseModel):
    """One execution of a pipeline (run history)."""

    id: uuid.UUID
    pipeline_id: uuid.UUID
    status: str
    dagster_run_id: str | None
    rows: int | None
    started_at: datetime.datetime | None
    finished_at: datetime.datetime | None
    error: str | None
    created_at: datetime.datetime


class PipelineRunSummary(PipelineRunRead):
    """A run with its pipeline's name — the tenant-wide monitoring feed.

    Adds ``pipeline_name`` so the Operations view can show recent runs across all
    of the tenant's pipelines without an extra per-run lookup.
    """

    pipeline_name: str
