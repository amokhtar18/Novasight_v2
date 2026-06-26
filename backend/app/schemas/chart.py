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
from app.schemas.semantic import OrderDir, SemanticFilter, SemanticRef, SemanticTimeDimension

# The current contract version. Bump when the shape changes in a breaking way so
# stored specs and AI-emitted specs can be migrated rather than silently misread.
CHART_SPEC_VERSION = "2"

# A reference to a column in a ``QueryResponse`` (or a semantic metric/dimension
# name). Bounded and pattern-checked so a spec can't smuggle arbitrary text into a
# display channel; dotted names like ``orders.revenue`` are allowed for the
# semantic-layer path.
FieldName = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_.]*$", min_length=1, max_length=128),
]

# The chart kinds the renderer supports (v2, #8). The original set plus a curated,
# Superset-inspired expansion. ``table``/``number``/``gauge`` present a result without a
# category axis; the rest map onto the shared ``x`` + ``series`` encoding:
#   bar/line/area/scatter — as before;          hbar — horizontal bar;
#   pie/donut — share-of-total;                  combo — first series bar, rest line;
#   funnel/treemap — labelled magnitudes;        radar — series as polygons over x;
#   gauge — a single KPI dial.
ChartType = Literal[
    "bar",
    "hbar",
    "line",
    "area",
    "combo",
    "pie",
    "donut",
    "scatter",
    "funnel",
    "treemap",
    "radar",
    "gauge",
    "table",
    "number",
]


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
    # Plain (non-time) governed dimensions to group by for a semantic chart. The first
    # is the chart's category axis (``encoding.x``); any others are *breakdown*
    # dimensions pivoted into series (``encoding.breakdown``). Carried on the spec so a
    # saved/AI chart re-runs the same multi-dimension grouping. Backward compatible:
    # legacy single-dimension specs leave this empty and the dimension lives on
    # ``encoding.x`` alone.
    dimensions: list[FieldName] = Field(default_factory=list)
    # Optional time dimensions for a semantic chart (the ``metric_refs`` path). Carried
    # on the spec so a saved/AI chart re-runs with the same granularity rollup; the
    # resolved key (``<dimension>.<granularity>``) is what ``encoding.x`` reads.
    time_dimensions: list[SemanticTimeDimension] = Field(default_factory=list)
    # Optional governed filters carried on the spec so a saved chart re-runs with the
    # same constraints. Each member is re-validated against the governed allow-list by
    # the semantic service before any Cube call (golden rule #3).
    filters: list[SemanticFilter] = Field(default_factory=list)
    # Optional server-side ordering, e.g. {"sales.total": "desc"}. Keys must be members
    # selected by this query; the service rejects anything else.
    order: dict[SemanticRef, OrderDir] = Field(default_factory=dict)
    # Optional per-chart row cap; the service clamps it to settings.max_query_rows.
    limit: int | None = Field(default=None, ge=1)

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
    # Breakdown dimensions: governed dimension columns (from ``query.dimensions``) whose
    # values are pivoted into one series each at render time. When present, the first
    # entry of ``series`` is the measure that supplies the pivoted values. Empty for a
    # plain chart where ``series`` already lists the measures to plot directly.
    breakdown: list[FieldName] = Field(default_factory=list)


# A hex colour for a custom palette entry (``#rgb`` … ``#rrggbbaa``).
HexColor = Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{3,8}$")]


class NumberFormat(BaseModel):
    """How numeric values are formatted in labels, tooltips, and value axes (#8)."""

    style: Literal["plain", "currency", "percent"] = "plain"
    # Fixed decimal places; None lets the renderer choose a sensible default.
    decimals: int | None = Field(default=None, ge=0, le=10)
    # Compact magnitudes (1.2K, 3.4M) for big numbers.
    compact: bool = False
    # Currency symbol/code for the ``currency`` style (e.g. "$", "€", "USD").
    currency: str | None = Field(default=None, max_length=8)
    # Optional prefix/suffix rendered around the formatted value (e.g. "≈", " net").
    prefix: str | None = Field(default=None, max_length=8)
    suffix: str | None = Field(default=None, max_length=8)


class LegendOptions(BaseModel):
    show: bool = True
    position: Literal["top", "bottom", "left", "right"] = "top"
    type: Literal["scroll", "plain"] = "scroll"
    margin: int | None = Field(default=None, ge=0, le=200)
    sort: Literal["none", "asc", "desc"] = "none"


class LabelOptions(BaseModel):
    show: bool = False
    position: str | None = None
    template: str | None = Field(default=None, max_length=200)
    threshold: float | None = Field(default=None, ge=0)


class TooltipOptions(BaseModel):
    mode: Literal["item", "axis", "rich"] = "axis"
    sort_by_metric: bool = False
    show_total: bool = False
    show_percentage: bool = False
    time_format: str | None = Field(default=None, max_length=64)


class CartesianOptions(BaseModel):
    """Per-chart-family display options for bar / line / area / hbar / combo / scatter."""

    stacked: bool = False
    percent: bool = False
    only_total: bool = False
    label_threshold: float | None = None
    area_opacity: float | None = Field(default=None, ge=0, le=1)
    markers: bool = False
    marker_size: int | None = Field(default=None, ge=1, le=50)
    smooth: bool = False
    x_axis_label: str | None = None
    y_axis_label: str | None = None
    x_label_rotation: Literal[0, 45, 90] | None = None
    x_label_interval: Literal["auto", "all"] = "auto"
    y_min: float | None = None
    y_max: float | None = None
    log_scale: bool = False
    minor_ticks: bool = False
    minor_split_line: bool = False
    data_zoom: bool = False
    sort_series: Literal["none", "asc", "desc"] = "none"


class PieOptions(BaseModel):
    """Per-chart-family display options for pie / donut."""

    label_type: Literal[
        "category",
        "value",
        "percent",
        "category_value",
        "value_percent",
        "category_value_percent",
    ] = "value"
    inner_radius: int | None = Field(default=None, ge=0, le=100)
    outer_radius: int | None = Field(default=None, ge=0, le=100)
    rose_type: Literal["none", "area", "radius"] = "none"
    labels_outside: bool = False
    label_line: bool = False
    show_total: bool = False
    show_labels_threshold: float | None = None
    group_others_threshold: float | None = None


class GaugeOptions(BaseModel):
    """Per-chart-family display options for gauge."""

    min: float | None = None
    max: float | None = None
    start_angle: float | None = None
    end_angle: float | None = None
    show_pointer: bool = True
    show_progress: bool = False
    round_cap: bool = False
    show_axis_tick: bool = False
    show_split_line: bool = False
    split_number: int | None = Field(default=None, ge=3, le=30)
    intervals: list[float] = Field(default_factory=list, max_length=12)
    interval_colors: list[HexColor] = Field(default_factory=list, max_length=12)
    font_size: int | None = Field(default=None, ge=10, le=20)
    animation: bool = True

    @model_validator(mode="after")
    def _intervals_match_colors(self) -> GaugeOptions:
        if (
            self.intervals
            and self.interval_colors
            and len(self.intervals) != len(self.interval_colors)
        ):
            raise ValueError("gauge interval_colors length must match intervals length")
        return self


class FunnelOptions(BaseModel):
    """Per-chart-family display options for funnel."""

    label_type: Literal[
        "none", "value", "percent", "category", "category_value", "value_percent", "all"
    ] = "value"
    tooltip_label_type: Literal[
        "value", "percent", "category", "category_value", "value_percent", "all"
    ] = "value"
    show_labels: bool = True
    show_tooltip_labels: bool = True


class MetricBound(BaseModel):
    """Min/max bound for a single metric on a radar chart."""

    min: float | None = None
    max: float | None = None


class RadarOptions(BaseModel):
    """Per-chart-family display options for radar."""

    shape: Literal["polygon", "circle"] = "polygon"
    label_type: Literal["value", "category_value"] = "value"
    label_position: str | None = None
    metric_bounds: dict[FieldName, MetricBound] = Field(default_factory=dict)


class TreemapOptions(BaseModel):
    """Per-chart-family display options for treemap."""

    show_labels: bool = True
    show_upper_labels: bool = False
    label_type: Literal["key", "value", "key_value"] = "key"


class NumberOptions(BaseModel):
    """Per-chart-family display options for number (KPI tile)."""

    subheader: str | None = Field(default=None, max_length=200)
    subtitle: str | None = Field(default=None, max_length=200)
    header_font_size: int | None = Field(default=None, ge=8, le=120)
    subheader_font_size: int | None = Field(default=None, ge=8, le=120)


class TypeOptions(BaseModel):
    """Aggregated per-family options bag. Only the relevant family key is set."""

    cartesian: CartesianOptions | None = None
    pie: PieOptions | None = None
    gauge: GaugeOptions | None = None
    funnel: FunnelOptions | None = None
    radar: RadarOptions | None = None
    treemap: TreemapOptions | None = None
    number: NumberOptions | None = None


class ChartOptions(BaseModel):
    """Display-only options (v2). Cross-type chrome here; per-type options in type_options."""

    title: str | None = None
    color_scheme: str | None = Field(default=None, max_length=64)
    # Optional palette overriding the theme's default colours.
    palette: list[HexColor] = Field(default_factory=list, max_length=24)
    legend: LegendOptions = Field(default_factory=LegendOptions)
    number_format: NumberFormat = Field(default_factory=NumberFormat)
    date_format: str | None = Field(default=None, max_length=64)
    labels: LabelOptions = Field(default_factory=LabelOptions)
    tooltip: TooltipOptions = Field(default_factory=TooltipOptions)
    # Client-side category reorder (distinct from query.order server sort).
    sort: Literal["none", "value_desc", "value_asc", "label_asc", "label_desc"] = "none"
    type_options: TypeOptions | None = None


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
        # Axis/label charts need a category axis; a pie/funnel/treemap needs a label
        # column too. ``table``, ``number`` and ``gauge`` present a single result or a
        # raw table without an axis, so they may omit ``x``.
        if self.type not in ("table", "number", "gauge") and self.encoding.x is None:
            raise ValueError(f"chart type '{self.type}' requires encoding.x")
        return self


# Rebuild ChartOptions now that TypeOptions has been fully defined (resolves the
# forward reference that ChartOptions.type_options carries).
ChartOptions.model_rebuild()
