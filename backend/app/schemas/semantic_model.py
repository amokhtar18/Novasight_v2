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

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

from app.core.sql_expression import validate_expression

# A SQL-safe identifier (member name, base table, join key). No dots, no expressions.
Identifier = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", min_length=1, max_length=128),
]

# Cube measure aggregation types (closed set).
MeasureType = Literal["count", "sum", "avg", "min", "max", "count_distinct"]

# Cube dimension types (closed set).
DimensionType = Literal["string", "number", "time", "boolean"]

# Cube join cardinality (closed set).
JoinRelationship = Literal["one_to_one", "one_to_many", "many_to_one"]


class MeasureDef(BaseModel):
    """One governed measure, e.g. ``sum(amount)`` or ``sum(if(paid, amount, 0))``.

    ``sql`` is the column or **validated expression** to aggregate (#6) — a bare
    column name still works, but window/string/CASE expressions are now allowed,
    bounded by the member-expression allow-list. Optional only for ``count``.
    """

    name: Identifier
    type: MeasureType
    sql: str | None = Field(default=None, max_length=1000)
    title: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=1000)

    @field_validator("sql")
    @classmethod
    def _validate_sql(cls, value: str | None) -> str | None:
        return None if value is None else validate_expression(value)

    @model_validator(mode="after")
    def _require_sql_for_non_count(self) -> MeasureDef:
        if self.type != "count" and self.sql is None:
            raise ValueError(f"measure '{self.name}' ({self.type}) requires a 'sql' column")
        return self


class DimensionDef(BaseModel):
    """One governed dimension — a column or **validated expression** for grouping (#6)."""

    name: Identifier
    type: DimensionType
    sql: str = Field(..., max_length=1000)
    title: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    primary_key: bool = False

    @field_validator("sql")
    @classmethod
    def _validate_sql(cls, value: str) -> str:
        return validate_expression(value)


class JoinDef(BaseModel):
    """A join to another cube: ``this.local_key = <name>.foreign_key`` (#6 multi-column).

    ``name`` is the **target cube** (another semantic model). The join is expressed only
    as equalities of **column identifiers** plus a closed ``relationship`` literal — no
    free SQL — so the codegen renders it injection-free.

    Two equivalent forms are accepted: the single-key ``local_key``/``foreign_key`` (kept
    for backward compatibility with stored models) or the composite ``local_keys``/
    ``foreign_keys`` lists (equal length, non-empty) for multi-column joins. Use
    ``key_pairs`` to read the normalised ``(local, foreign)`` pairs.
    """

    name: Identifier
    relationship: JoinRelationship
    local_key: Identifier | None = None
    foreign_key: Identifier | None = None
    local_keys: list[Identifier] = Field(default_factory=list, max_length=16)
    foreign_keys: list[Identifier] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def _validate_keys(self) -> JoinDef:
        if self.local_keys or self.foreign_keys:
            if not self.local_keys or len(self.local_keys) != len(self.foreign_keys):
                raise ValueError(
                    "local_keys and foreign_keys must be non-empty and the same length"
                )
        elif not (self.local_key and self.foreign_key):
            raise ValueError(
                "a join needs local_key+foreign_key or local_keys+foreign_keys"
            )
        return self

    @property
    def key_pairs(self) -> list[tuple[str, str]]:
        """Normalised ``(local, foreign)`` equality pairs (single- or multi-column)."""
        if self.local_keys:
            return list(zip(self.local_keys, self.foreign_keys, strict=True))
        assert self.local_key is not None and self.foreign_key is not None
        return [(self.local_key, self.foreign_key)]


class SemanticModelConfig(BaseModel):
    """The wizard payload: the measures + dimensions (+ joins) of a model."""

    measures: list[MeasureDef] = Field(default_factory=list)
    dimensions: list[DimensionDef] = Field(default_factory=list)
    joins: list[JoinDef] = Field(default_factory=list)

    @model_validator(mode="after")
    def _require_members_and_unique_names(self) -> SemanticModelConfig:
        if not self.measures and not self.dimensions:
            raise ValueError("a semantic model needs at least one measure or dimension")
        names = [m.name for m in self.measures] + [d.name for d in self.dimensions]
        if len(names) != len(set(names)):
            raise ValueError("measure/dimension names must be unique within a model")
        join_targets = [j.name for j in self.joins]
        if len(join_targets) != len(set(join_targets)):
            raise ValueError("a model can join each target cube at most once")
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
