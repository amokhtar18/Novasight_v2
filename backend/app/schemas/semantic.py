"""Schemas for the governed semantic-layer query API (feature #9).

The manual chart builder queries the *semantic layer*, never raw physical tables:
the client picks governed measures/dimensions from a model and the backend resolves
them through Cube, scoped to the tenant's ``clickhouse_db`` (golden rule #3). This is
the structured, grounded analogue of the AI ``NL→chart`` path — same renderer, same
``QueryResponse`` shape — but driven by point-and-click instead of an LLM.

Field references are the fully-qualified Cube identifiers (e.g.
``regional_sales.total_amount``); the dotted form is allowed by the pattern below.
The service validates every reference against the tenant's governed meta before any
query runs, so a caller can never reach a measure/dimension Cube does not expose.
"""
from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, model_validator

# A governed Cube identifier: ``cube`` or ``cube.member``. Bounded and
# pattern-checked at the boundary so an invalid name is a 422 before any Cube call
# (the service additionally checks it against the governed allow-list).
SemanticRef = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_.]*$", min_length=1, max_length=128),
]

# Ordering direction Cube accepts.
OrderDir = Annotated[str, StringConstraints(pattern=r"^(asc|desc)$")]


class SemanticField(BaseModel):
    """One governed measure or dimension exposed by a model."""

    name: str = Field(description="Fully-qualified Cube identifier, e.g. 'sales.region'.")
    title: str = Field(description="Human-readable label for display in the builder.")
    type: str = Field(description="Cube member type (e.g. 'number', 'string', 'time').")


class SemanticModelRead(BaseModel):
    """A governed model (Cube cube/view) the tenant may query.

    Derived from Cube's ``/meta`` response for the current tenant — it lists only
    what Cube exposes, so the builder can never offer a raw physical table.
    """

    name: str = Field(description="Cube identifier of the model.")
    title: str = Field(description="Human-readable model label.")
    measures: list[SemanticField] = Field(description="Governed measures.")
    dimensions: list[SemanticField] = Field(description="Governed dimensions.")


class SemanticQueryRequest(BaseModel):
    """A structured query against the semantic layer.

    At least one measure or dimension is required. Identifiers are constrained at
    the boundary and re-checked against the governed allow-list in the service.
    """

    measures: list[SemanticRef] = Field(default_factory=list)
    dimensions: list[SemanticRef] = Field(default_factory=list)
    # Optional ordering: ``{"sales.total_amount": "desc"}``. Keys must be queried
    # members; the service rejects anything not in measures/dimensions.
    order: dict[SemanticRef, OrderDir] = Field(default_factory=dict)
    # Per-request row cap; the service clamps it to ``settings.max_query_rows`` so a
    # caller can never exceed the platform limit.
    limit: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _require_a_field(self) -> SemanticQueryRequest:
        if not self.measures and not self.dimensions:
            raise ValueError("a semantic query needs at least one measure or dimension")
        return self
