"""Schemas for the semantic-model *registry* (the wizard's definitions) — #8.

These define a governed model the user builds over a serving table (a dbt mart):
its measures and dimensions. The codegen layer renders a stored definition into a
Cube model file (see ``app.codegen.cube_model``); the read-only query path (#9) then
sees it as a governed cube via Cube ``/meta``.

Everything that reaches the generated Cube file is constrained here: member names and
SQL column references are strict identifiers (no arbitrary SQL), and measure/dimension
types are closed ``Literal`` sets. Titles/descriptions are bounded free text and are
JSON-encoded by the codegen, so they cannot break out of the template. This is the
same defense-in-depth posture as the structured query path.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

# A SQL-safe identifier (member name or a column reference). No dots, no expressions —
# richer SQL is a later (Phase 2) concern; the slice stays injection-proof by design.
Identifier = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", min_length=1, max_length=128),
]

# Cube measure aggregation types (closed set).
MeasureType = Literal["count", "sum", "avg", "min", "max", "count_distinct"]

# Cube dimension types (closed set).
DimensionType = Literal["string", "number", "time", "boolean"]


class MeasureDef(BaseModel):
    """One governed measure, e.g. ``sum(amount) AS total_amount``."""

    name: Identifier
    type: MeasureType
    # The column to aggregate. Optional only for ``count`` (→ ``count(*)``).
    sql: Identifier | None = None
    title: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _require_sql_for_non_count(self) -> MeasureDef:
        if self.type != "count" and self.sql is None:
            raise ValueError(f"measure '{self.name}' ({self.type}) requires a 'sql' column")
        return self


class DimensionDef(BaseModel):
    """One governed dimension (a column exposed for grouping/filtering)."""

    name: Identifier
    type: DimensionType
    sql: Identifier
    title: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    primary_key: bool = False


class SemanticModelConfig(BaseModel):
    """The wizard payload: the measures + dimensions of a model."""

    measures: list[MeasureDef] = Field(default_factory=list)
    dimensions: list[DimensionDef] = Field(default_factory=list)

    @model_validator(mode="after")
    def _require_members_and_unique_names(self) -> SemanticModelConfig:
        if not self.measures and not self.dimensions:
            raise ValueError("a semantic model needs at least one measure or dimension")
        names = [m.name for m in self.measures] + [d.name for d in self.dimensions]
        if len(names) != len(set(names)):
            raise ValueError("measure/dimension names must be unique within a model")
        return self


class SemanticModelCreate(BaseModel):
    """Body for ``POST /semantic-models``."""

    name: Identifier
    base_table: Identifier
    config: SemanticModelConfig
    enabled: bool = True


class SemanticModelUpdate(BaseModel):
    """Body for ``PATCH /semantic-models/{id}`` — partial."""

    name: Identifier | None = None
    base_table: Identifier | None = None
    config: SemanticModelConfig | None = None
    enabled: bool | None = None


class SemanticModelDefRead(BaseModel):
    """A stored semantic-model definition as returned to clients."""

    id: uuid.UUID
    name: str
    base_table: str
    config: SemanticModelConfig
    enabled: bool
    created_at: datetime
    updated_at: datetime
