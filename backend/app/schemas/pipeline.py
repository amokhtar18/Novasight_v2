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

from pydantic import BaseModel, Field, StringConstraints, model_validator

# Iceberg/ClickHouse table identifier (target landing table). Also used for column
# identifiers the executor interpolates into SQL (keys, partition, filter columns),
# so the strict charset doubles as the injection guard.
Identifier = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", min_length=1, max_length=128),
]

# How a run lands its data:
#   overwrite   — full reload, replace the target (the original behaviour, default)
#   append      — add rows, no key dedupe
#   merge       — upsert by primary_key (SCD type 1 in effect)
#   incremental — append only rows newer than the last cdc_column high-water mark
WriteDisposition = Literal["overwrite", "append", "merge", "incremental"]

# Canonical destination types the field map offers (mirrors ingestion.type_mapping).
TargetType = Literal[
    "String", "Int64", "Float64", "Decimal", "Boolean", "Date", "DateTime", "JSON", "UUID"
]

# Slowly-changing-dimension handling. scd2 (history) is accepted + stored so the UI
# can offer it, but rejected at execute for now (the executor implements none/scd1).
ScdType = Literal["none", "scd1", "scd2"]

# Structured filter operators (closed set — see FilterClause).
FilterOperator = Literal[
    "eq", "ne", "gt", "ge", "lt", "le", "like", "in", "is_null", "is_not_null"
]


class ColumnMap(BaseModel):
    """One source column mapped to a destination column (#5).

    ``included`` toggles whether the column is extracted; ``target_name`` renames it
    in the landing table; ``target_type`` is a closed destination type (defaulted from
    the source type by the wizard, overridable). ``source_name`` is the raw column name
    as the source reports it (not a strict identifier — only ``target_name``, which we
    emit, is); ``source_type`` is informational.
    """

    source_name: str = Field(..., min_length=1, max_length=255)
    source_type: str = Field(default="", max_length=128)
    target_name: Identifier
    target_type: TargetType = "String"
    included: bool = True


class FilterClause(BaseModel):
    """A structured source-side predicate (filter push-down, #6).

    Deliberately *not* free-form SQL: ``column`` is a strict identifier, ``operator`` is
    a closed set, and ``value`` is bound as a parameter by the executor — so a stored
    filter can never inject SQL (see the security note in the ETL docs / plan).
    """

    column: Identifier
    operator: FilterOperator
    value: str | int | float | bool | list[str | int | float] | None = None

    @model_validator(mode="after")
    def _value_matches_operator(self) -> FilterClause:
        nullary = self.operator in ("is_null", "is_not_null")
        if nullary and self.value is not None:
            raise ValueError(f"{self.operator} takes no value")
        if not nullary and self.value is None:
            raise ValueError(f"{self.operator} requires a value")
        if self.operator == "in" and not isinstance(self.value, list):
            raise ValueError("in requires a list value")
        return self


class PipelineConfig(BaseModel):
    """Selection + load options for one pipeline."""

    # The source object to extract: a DB table name, or a file key/path for filesystem.
    object: str = Field(..., min_length=1, max_length=512)
    write_disposition: WriteDisposition = "overwrite"
    # Source schema the object lives in (relational sources; None = default schema).
    source_schema: str | None = Field(default=None, max_length=255)
    # Field-level map; empty = extract every column as-is (the original behaviour).
    columns: list[ColumnMap] = Field(default_factory=list, max_length=512)
    # Upsert/dedupe key (required for merge/scd1/scd2); references target columns.
    primary_key: list[Identifier] = Field(default_factory=list, max_length=16)
    # Optional partition columns for the Iceberg landing table.
    partition_by: list[Identifier] = Field(default_factory=list, max_length=8)
    # Source-side predicates (AND-ed) pushed into the extract query.
    source_filters: list[FilterClause] = Field(default_factory=list, max_length=32)
    # Slowly-changing-dimension strategy + the change-tracking (CDC) column.
    scd_type: ScdType = "none"
    cdc_column: Identifier | None = None

    @model_validator(mode="after")
    def _load_mode_requirements(self) -> PipelineConfig:
        needs_key = self.write_disposition == "merge" or self.scd_type in ("scd1", "scd2")
        if needs_key and not self.primary_key:
            raise ValueError("merge / SCD load requires at least one primary_key column")
        if self.write_disposition == "incremental" and not self.cdc_column:
            raise ValueError("incremental load requires a cdc_column")
        # Unique target names when a field map is provided.
        targets = [c.target_name for c in self.columns]
        if len(targets) != len(set(targets)):
            raise ValueError("column target_name values must be unique")
        return self


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
