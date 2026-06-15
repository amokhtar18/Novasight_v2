"""The shared **chart-spec** contract (Task 3.1).

A ``ChartSpec`` is a declarative description of *one chart*: what kind of chart it
is, where its data comes from, how result columns map onto visual channels, and a
handful of display options. It is deliberately renderer-agnostic — the frontend
turns it into an ECharts option, but nothing here mentions ECharts.

This is the single shape produced by **both** paths:

* manual configuration in the low-code builder / explore view, and
* the AI ``NL→chart`` endpoint in a later phase.

Because both emit the same shape, manual and AI charts share one renderer. The
TypeScript mirror lives in ``frontend/src/types/api.ts`` and the contract is
documented in ``docs/CHART_SPEC.md``. Field names are snake_case so the JSON that
crosses the wire is identical on both sides (see ``tests/test_chart_spec.py`` for
the round-trip proof).

The spec carries no SQL: the structured ``QueryRequest`` it references is compiled
to a read-only ``SELECT`` by the query service, and the encoding ``field`` values
are just *display references* to columns in the ``QueryResponse`` — they never
reach the SQL builder. See the ``query`` schema and the ``tenancy-isolation`` and
``nl-to-sql-grounding`` skills.
"""
from __future__ import annotations

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.schemas.query import QueryRequest
from app.schemas.semantic import SemanticTimeDimension

# The current contract version. Bump when the shape changes in a breaking way so
# stored specs and AI-emitted specs can be migrated rather than silently misread.
CHART_SPEC_VERSION = "1"

# A reference to a column in a ``QueryResponse`` (or a semantic metric/dimension
# name). Bounded and pattern-checked so a spec can't smuggle arbitrary text into a
# display channel; dotted names like ``orders.revenue`` are allowed for the
# semantic-layer path.
FieldName = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_.]*$", min_length=1, max_length=128),
]

# The chart kinds the renderer supports. ``table`` and ``number`` are included in
# the contract (both are valid ways to present a query result) even though they are
# not x/series charts; the renderer handles them specially. ``number`` is a single
# "big number" KPI (the total of its series across the result). ``scatter`` plots
# each series against a numeric ``x`` (a value axis, not categories).
ChartType = Literal["bar", "line", "area", "pie", "table", "number", "scatter"]


class ChartQuery(BaseModel):
    """Where a chart's data comes from.

    Two grounded sources are supported, and at least one must be present:

    * an inline structured ``query`` against a ``dataset_id`` (the Phase 1 path),
      compiled to a safe read-only aggregation by the query service; and/or
    * ``metric_refs`` — names of governed metrics resolved by the semantic layer
      (the path the AI layer will use).

    A raw SQL string is intentionally *not* a source — there is nowhere to put one.
    """

    dataset_id: uuid.UUID | None = None
    query: QueryRequest | None = None
    metric_refs: list[FieldName] = Field(default_factory=list)
    # Optional time dimensions for a semantic chart (the ``metric_refs`` path). Carried
    # on the spec so a saved/AI chart re-runs with the same granularity rollup; the
    # resolved key (``<dimension>.<granularity>``) is what ``encoding.x`` reads.
    time_dimensions: list[SemanticTimeDimension] = Field(default_factory=list)

    @model_validator(mode="after")
    def _require_a_source(self) -> ChartQuery:
        if self.query is None and not self.metric_refs:
            raise ValueError(
                "a ChartQuery needs an inline 'query' or at least one 'metric_refs' entry"
            )
        return self


class SeriesEncoding(BaseModel):
    """One plotted series: which result column to read, and how to label it."""

    field: FieldName
    # Legend label. Defaults to the field name when omitted (resolved in the UI).
    name: str | None = None
    # Optional explicit colour (e.g. ``"#3b82f6"``); the renderer picks one if None.
    color: str | None = None


class ChartEncoding(BaseModel):
    """How query columns map onto the chart's visual channels.

    ``x`` is the category axis (x axis for bar/line/area, the slice label for pie).
    ``series`` lists the value series; for a ``table`` chart the series are simply
    the columns to display.
    """

    x: FieldName | None = None
    series: list[SeriesEncoding] = Field(min_length=1)


class ChartOptions(BaseModel):
    """Display-only options. None of these affect the query or the data."""

    title: str | None = None
    stacked: bool = False
    show_legend: bool = True
    x_axis_label: str | None = None
    y_axis_label: str | None = None


class ChartSpec(BaseModel):
    """A complete, self-contained description of one chart.

    The four parts mirror the contract task: ``type`` (chart type), ``query``
    (query/metric refs), ``encoding`` (encodings), and ``options``.
    """

    version: str = CHART_SPEC_VERSION
    type: ChartType
    query: ChartQuery
    encoding: ChartEncoding
    options: ChartOptions = Field(default_factory=ChartOptions)

    @model_validator(mode="after")
    def _require_x_for_axis_charts(self) -> ChartSpec:
        # Axis charts are meaningless without a category axis; a pie needs a label
        # column too. ``table`` and ``number`` present a result without an axis, so
        # they may omit ``x``.
        if self.type not in ("table", "number") and self.encoding.x is None:
            raise ValueError(f"chart type '{self.type}' requires encoding.x")
        return self
