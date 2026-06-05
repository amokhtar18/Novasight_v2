"""Request/response schemas for the dataset aggregation query endpoint (Task 1.4).

The query API is deliberately **structured, not free SQL**: the client describes an
aggregation (group-by dimensions + aggregate metrics + optional filters) and the
service compiles it into a single read-only ``SELECT``. This is what makes it safe —
there is no place for a caller to inject SQL:

* identifiers (column names, aliases) are constrained to a strict ``[A-Za-z_]\\w*``
  pattern at the schema boundary, so an invalid name is rejected with a 422 before any
  SQL is built (and the service still backtick-quotes them defensively);
* aggregate functions and filter operators are closed ``Literal`` sets;
* filter *values* are bound as ClickHouse query parameters, never interpolated.

See the ``tenancy-isolation`` and ``fastapi-conventions`` skills.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

# A SQL-safe identifier: starts with a letter/underscore, then word chars only. Column
# and alias names that reach the SQL builder must match this; anything else is a 422.
Identifier = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", min_length=1, max_length=128),
]

# Aggregate functions the endpoint supports — a closed set, never caller-supplied SQL.
AggFunction = Literal["count", "sum", "avg", "min", "max"]

# Comparison operators allowed in a filter — also a closed set.
FilterOp = Literal["=", "!=", "<", "<=", ">", ">="]


class Metric(BaseModel):
    """One aggregate measure, e.g. ``sum(amount) AS total``."""

    function: AggFunction
    # Required for every function except ``count`` (which becomes ``count(*)`` when omitted).
    column: Identifier | None = None
    alias: Identifier | None = None

    @model_validator(mode="after")
    def _require_column_for_non_count(self) -> Metric:
        if self.function != "count" and self.column is None:
            raise ValueError(f"metric '{self.function}' requires a column")
        return self


class Filter(BaseModel):
    """A single ``column <op> value`` predicate. ``value`` is bound as a parameter."""

    column: Identifier
    op: FilterOp
    value: str | int | float | bool


class QueryRequest(BaseModel):
    """A structured aggregation request against one dataset.

    At least one metric is required. With no dimensions the result is a single global
    aggregate row; with dimensions the metrics are grouped by them.
    """

    dimensions: list[Identifier] = Field(default_factory=list)
    metrics: list[Metric] = Field(min_length=1)
    filters: list[Filter] = Field(default_factory=list)
    # Per-request row cap; the service additionally clamps this to the configured
    # ``max_query_rows`` so a caller can never exceed the platform limit.
    limit: int | None = Field(default=None, ge=1)


class QueryResponse(BaseModel):
    """Aggregated result: ordered column names + row values, plus the row count."""

    columns: list[str]
    rows: list[list[Any]]
    row_count: int
