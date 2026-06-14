"""Schemas for the dbt model + test wizard registry (#5/#6).

A ``DbtModel`` is a wizard-authored transformation: a ``layer``, a
``materialization``, and the model ``sql`` (a SELECT). Attached ``DbtTest`` rows
become dbt data tests (surfaced later as Dagster asset checks). The codegen
(``app.codegen.dbt_model``) renders these into the per-tenant dbt project.

The model ``name`` is a strict identifier (it is the dbt model name + filename).
``layer``/``materialization``/``test_type`` are closed ``Literal`` sets. The model
``sql`` is the user's transformation (custom SQL is a first-class dbt path) — it is
authored by a tenant superuser and compiled by dbt, not interpolated by us.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

Identifier = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", min_length=1, max_length=128),
]

Layer = Literal["staging", "intermediate", "marts"]
Materialization = Literal["view", "table", "incremental"]
TestType = Literal["not_null", "unique", "accepted_values", "relationships"]
# dbt incremental strategies (closed set) and schema-evolution policy.
IncrementalStrategy = Literal["append", "merge", "delete+insert", "insert_overwrite"]
OnSchemaChange = Literal["ignore", "fail", "append_new_columns", "sync_all_columns"]


class IncrementalConfig(BaseModel):
    """dbt incremental settings — only applied when ``materialization='incremental'``.

    ``unique_key`` is one or more **column identifiers** (so an incremental run can
    upsert rather than blindly append); strategy and schema-change policy are closed
    sets. Everything here is a validated identifier or a ``Literal``, so the codegen
    can interpolate it into the ``{{ config(...) }}`` header injection-free.
    """

    unique_key: list[Identifier] = Field(default_factory=list, max_length=16)
    incremental_strategy: IncrementalStrategy | None = None
    on_schema_change: OnSchemaChange | None = None


class DbtTestDef(BaseModel):
    """A data test on a model (column-level when ``column_name`` is set)."""

    column_name: Identifier | None = None
    test_type: TestType
    # Extra params: accepted_values → {"values": [...]}; relationships → {"to","field"}.
    config: dict[str, Any] = Field(default_factory=dict)


class DbtModelCreate(BaseModel):
    """Body for ``POST /dbt-models``."""

    name: Identifier
    layer: Layer = "marts"
    materialization: Materialization = "table"
    sql: str = Field(..., min_length=1, max_length=20000)
    config: dict[str, Any] = Field(default_factory=dict)
    incremental: IncrementalConfig | None = None
    tests: list[DbtTestDef] = Field(default_factory=list)
    enabled: bool = True

    @model_validator(mode="after")
    def _incremental_only_for_incremental(self) -> DbtModelCreate:
        if self.incremental is not None and self.materialization != "incremental":
            raise ValueError(
                "incremental settings require materialization='incremental'"
            )
        return self


class DbtModelUpdate(BaseModel):
    """Body for ``PATCH /dbt-models/{id}`` — partial. ``tests`` (if given) replaces all."""

    name: Identifier | None = None
    layer: Layer | None = None
    materialization: Materialization | None = None
    sql: str | None = Field(default=None, min_length=1, max_length=20000)
    config: dict[str, Any] | None = None
    incremental: IncrementalConfig | None = None
    tests: list[DbtTestDef] | None = None
    enabled: bool | None = None


class DbtTestRead(BaseModel):
    """A stored data test."""

    id: uuid.UUID
    column_name: str | None
    test_type: str
    config: dict[str, Any]


class DbtModelRead(BaseModel):
    """A stored dbt model definition."""

    id: uuid.UUID
    name: str
    layer: str
    materialization: str
    sql: str | None
    config: dict[str, Any]
    # Typed view of the incremental settings stored in ``config`` (None unless set).
    incremental: IncrementalConfig | None = None
    enabled: bool
    tests: list[DbtTestRead]
    created_at: datetime
    updated_at: datetime
