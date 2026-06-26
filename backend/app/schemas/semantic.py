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

from datetime import date
from typing import Annotated, Literal

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

# Cube filter operators we expose (a closed set mapped 1:1 to Cube's operators).
FilterOperator = Literal[
    "equals",
    "notEquals",
    "contains",
    "notContains",
    "gt",
    "gte",
    "lt",
    "lte",
    "set",
    "notSet",
]

# Operators that are presence checks and so take no values.
_VALUELESS_OPERATORS = frozenset({"set", "notSet"})

# Cube time-dimension granularities (closed set, mapped 1:1 to Cube's). A query on a
# ``time``-typed dimension can roll it up to one of these buckets — the defining feature
# of a time dimension (e.g. "total_amount by month").
SemanticGranularity = Literal[
    "second",
    "minute",
    "hour",
    "day",
    "week",
    "month",
    "quarter",
    "year",
]

# Relative date-range tokens (closed set) → Cube's native relative range strings.
RelativeDateRange = Literal[
    "last_7_days",
    "last_30_days",
    "last_90_days",
    "this_month",
    "last_month",
    "this_quarter",
    "last_quarter",
    "this_year",
    "last_year",
]

_RELATIVE_TO_CUBE: dict[str, str] = {
    "last_7_days": "last 7 days",
    "last_30_days": "last 30 days",
    "last_90_days": "last 90 days",
    "this_month": "this month",
    "last_month": "last month",
    "this_quarter": "this quarter",
    "last_quarter": "last quarter",
    "this_year": "this year",
    "last_year": "last year",
}


class SemanticFilter(BaseModel):
    """A filter on a governed member: ``member <operator> values``.

    ``member`` is a governed measure or dimension (re-checked against the allow-list
    in the service, exactly like measures/dimensions — a filter is never a way to
    reach an ungoverned field). Operators map 1:1 to Cube's; ``set``/``notSet`` are
    presence checks that take no values, every other operator needs at least one.
    """

    member: SemanticRef
    operator: FilterOperator
    values: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def _values_match_operator(self) -> SemanticFilter:
        if self.operator in _VALUELESS_OPERATORS:
            if self.values:
                raise ValueError(f"operator '{self.operator}' takes no values")
        elif not self.values:
            raise ValueError(f"operator '{self.operator}' requires at least one value")
        return self


class SemanticTimeDimension(BaseModel):
    """A time dimension to group by, optionally rolled up to a ``granularity``.

    ``dimension`` is a governed dimension reference (re-checked against the allow-list
    in the service, exactly like a regular dimension — it must be a ``time``-typed
    member). With a ``granularity`` Cube buckets the values (e.g. by ``month``) and
    returns them under the ``<dimension>.<granularity>`` key; without one the raw time
    value is grouped (and returned under ``<dimension>``). That resolved key — see
    :attr:`result_key` — is the column the chart reads for its time axis.
    """

    dimension: SemanticRef
    granularity: SemanticGranularity | None = None
    # Optional time-range filter. Either a relative token (closed set) or an absolute
    # [from, to] pair of ISO dates. Maps to Cube's ``dateRange`` (see cube_date_range).
    date_range: RelativeDateRange | list[str] | None = None

    @model_validator(mode="after")
    def _validate_absolute_range(self) -> SemanticTimeDimension:
        if isinstance(self.date_range, list):
            if len(self.date_range) != 2:
                raise ValueError("an absolute date_range must be exactly two ISO dates")
            try:
                start, end = (date.fromisoformat(d) for d in self.date_range)
            except ValueError as exc:
                raise ValueError("date_range entries must be ISO dates (YYYY-MM-DD)") from exc
            if start > end:
                raise ValueError("date_range start must not be after end")
        return self

    @property
    def result_key(self) -> str:
        """The column key Cube returns this time dimension under."""
        if self.granularity is not None:
            return f"{self.dimension}.{self.granularity}"
        return self.dimension

    @property
    def cube_date_range(self) -> str | list[str] | None:
        """The Cube-native dateRange value (None when unset)."""
        if self.date_range is None:
            return None
        if isinstance(self.date_range, list):
            return list(self.date_range)
        return _RELATIVE_TO_CUBE[self.date_range]


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
    # Optional time dimensions to group by, each optionally rolled up to a granularity
    # (e.g. by month). Resolved through Cube's ``timeDimensions``; each ``dimension`` is
    # re-checked against the governed allow-list in the service.
    time_dimensions: list[SemanticTimeDimension] = Field(default_factory=list)
    # Optional ordering: ``{"sales.total_amount": "desc"}``. Keys must be queried
    # members (a measure, dimension, or a time dimension's resolved key); the service
    # rejects anything else.
    order: dict[SemanticRef, OrderDir] = Field(default_factory=dict)
    # Optional filters on governed members. Each member is re-checked against the
    # governed allow-list in the service (a filter never reaches an ungoverned field).
    filters: list[SemanticFilter] = Field(default_factory=list)
    # Per-request row cap; the service clamps it to ``settings.max_query_rows`` so a
    # caller can never exceed the platform limit.
    limit: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _require_a_field(self) -> SemanticQueryRequest:
        if not self.measures and not self.dimensions and not self.time_dimensions:
            raise ValueError(
                "a semantic query needs at least one measure, dimension, or time dimension"
            )
        return self


class SemanticValuesRequest(BaseModel):
    """Request distinct values for a governed dimension (filter dropdown / cascading).

    ``member`` must be a governed dimension. ``search`` is an optional substring
    (server-side typeahead → a ``contains`` filter). ``constraints`` are parent-filter
    selections (cascading). ``limit`` is clamped to ``settings.max_filter_values``.
    """

    member: SemanticRef
    search: str | None = Field(default=None, max_length=128)
    constraints: list[SemanticFilter] = Field(default_factory=list, max_length=20)
    # Per-request value cap; the service clamps it to ``settings.max_filter_values`` so a
    # caller can never exceed the platform limit (mirrors SemanticQueryRequest.limit).
    limit: int | None = Field(default=None, ge=1)


class SemanticValuesResponse(BaseModel):
    """Distinct values for a dimension (deduped, capped, ordered)."""

    values: list[str] = Field(default_factory=list)
