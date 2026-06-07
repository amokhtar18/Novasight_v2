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

from pydantic import BaseModel, Field, StringConstraints

Identifier = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", min_length=1, max_length=128),
]

Layer = Literal["staging", "intermediate", "marts"]
Materialization = Literal["view", "table", "incremental"]
TestType = Literal["not_null", "unique", "accepted_values", "relationships"]


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
    tests: list[DbtTestDef] = Field(default_factory=list)
    enabled: bool = True


class DbtModelUpdate(BaseModel):
    """Body for ``PATCH /dbt-models/{id}`` — partial. ``tests`` (if given) replaces all."""

    name: Identifier | None = None
    layer: Layer | None = None
    materialization: Materialization | None = None
    sql: str | None = Field(default=None, min_length=1, max_length=20000)
    config: dict[str, Any] | None = None
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
    enabled: bool
    tests: list[DbtTestRead]
    created_at: datetime
    updated_at: datetime
