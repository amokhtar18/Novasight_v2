# Superset-parity for charts & dashboards — Slice A2: Per-type formatting parity

**Date:** 2026-06-26
**Status:** Design approved (fresh-start, no backward compat); ready for implementation plan
**Depends on:** Slice A (chart-builder query shaping)
**Branch:** will get its own feature branch

---

## Program context

Second slice of the Superset-parity program (see
`2026-06-26-superset-parity-slice-a-builder-design.md` for the program overview and
golden-rule constraints). Sequence:

| Slice | Theme | Status |
|-------|-------|--------|
| A | Chart-builder (Explore) parity — query shaping + chart actions | spec done |
| **A2** | **Per-type formatting parity — Superset "Customize" panel** | **this spec** |
| C | Native filters — typed panel, scoping, cascading, drill | later |
| B | Dashboard layout — resize, rows/columns, tabs, header, fullscreen | later |
| D | More viz types & options — pivot, big-number trend, heatmap, box plot, conditional table formatting, annotations | later |

A2 comes right after A because both edit the builder's configure panel
(`FormatControls` / `SemanticQueryBuilder`); doing them back-to-back minimises churn.

---

## Goal

Reach parity with Superset's per-chart-type **Customize** panel: make NovaSight's
formatting controls **type-aware** and add every *meaningful* per-type option Superset
exposes for the equivalent ECharts viz. Today NovaSight applies a single flat
`FormatControls` (legend, sort, number format, decimals, currency, y-bounds, stacked,
data labels, compact, log scale) to all 14 chart types.

Formatting is **display-only**: none of these options touch the query, the data, the
tenant context, or the SQL/semantic layer. Golden rules are trivially satisfied —
the palette still derives from the theme, and nothing environment- or tenant-specific
is introduced (rule #1).

---

## Key decisions (approved)

1. **Nested per-type options**, realized as **family-keyed** sub-objects (not a strict
   14-way discriminated union). Flipping a type *within* a family (e.g. bar→line)
   keeps that family's settings; switching families reads a different sub-key (others
   lie dormant and are never shown). The user approved family-keying over a strict
   per-type union.
2. **Fresh start — no backward compatibility.** All type-specific options (including
   today's flat `stacked`, `percent`, `y_min`, `y_max`, `log_scale`, `x_axis_label`,
   `y_axis_label`) move into the nested structure; the legacy flat fields are
   **removed**. `CHART_SPEC_VERSION` is **bumped to `"2"`**. v1 specs are **not
   migrated** (acceptable: pre-production; few/no persisted specs). This is the
   program's single breaking-change checkpoint.
3. **"Every meaningful one"** — copy every option with a real effect in our ECharts
   renderer + Cube model; the explicit drop-list below is approved.

---

## Contract — the new `ChartSpec` v2 options shape

### Shared chrome — `ChartOptions` (applies to every type that supports it)

```
ChartOptions:
  title: str | None
  color_scheme: str | None          # named theme scheme → resolves to a palette
  palette: list[HexColor]           # explicit override (existing)
  legend:
    show: bool = True
    position: top | bottom | left | right = top
    type: scroll | plain = scroll   # NEW
    margin: int | None              # NEW
    sort: none | asc | desc = none  # NEW (legend item order)
  number_format:                    # existing structured model (kept; no D3 string)
    style: plain | currency | percent
    decimals: int | None
    compact: bool
    currency: str | None
    prefix: str | None              # NEW (value prefix, e.g. unit)
    suffix: str | None              # NEW (value suffix)
  date_format: str | None           # NEW — format for time axis labels & tooltips
  labels:                           # shared data-label block (universal bits only)
    show: bool = False
    position: str | None            # NEW (auto/top/inside/…); honoured where the type allows
    template: str | None            # NEW ({name}/{value}/{percent}); used by families that support it
    threshold: float | None         # NEW (min % to show a label)
    # NOTE: label *content* (label_type) is family-specific — its allowed values differ
    # per family (treemap key/value, radar value/category_value, pie/funnel category/
    # value/percent combos) — so it lives in each family's type_options, not here.
  tooltip:                          # shared tooltip block
    mode: item | axis | rich = axis # NEW
    sort_by_metric: bool = False    # NEW
    show_total: bool = False        # NEW
    show_percentage: bool = False   # NEW
    time_format: str | None         # NEW
  sort: none | value_desc | value_asc | label_asc | label_desc = none  # display reorder (kept)
  type_options: TypeOptions | None  # NEW — per-family options below
```

### `type_options` — one optional sub-object per family

**`cartesian`** (bar, hbar, line, area, combo, scatter)
```
stacked: bool = False
percent: bool = False            # 100%-stacked — NOW honoured in the renderer (today ignored)
only_total: bool = False         # show only the stack total label
label_threshold: float | None    # min value/% to render a point label
area_opacity: float | None       # area fill opacity (area type)
markers: bool = False            # show point markers (line/scatter)
marker_size: int | None
smooth: bool = False             # smooth lines
x_axis_label: str | None
y_axis_label: str | None
x_label_rotation: 0 | 45 | 90 | auto = auto
x_label_interval: auto | all     # show all x labels or auto-thin
y_min: float | None
y_max: float | None
log_scale: bool = False
minor_ticks: bool = False
minor_split_line: bool = False
data_zoom: bool = False          # interactive x zoom/pan
sort_series: none | asc | desc = none
```

**`pie`** (pie, donut)
```
label_type: category | value | percent | category_value | value_percent | category_value_percent = value
inner_radius: int | None         # % (donut hole); donut defaults non-zero
outer_radius: int | None         # %
rose_type: none | area | radius = none   # Nightingale
labels_outside: bool = False
label_line: bool = False         # connector line when labels outside
show_total: bool = False         # center total
show_labels_threshold: float | None
group_others_threshold: float | None     # slices below % grouped into "Other"
```

**`gauge`**
```
min: float | None
max: float | None
start_angle: float | None        # default 225
end_angle: float | None          # default -45
show_pointer: bool = True
show_progress: bool = False
round_cap: bool = False
show_axis_tick: bool = False
show_split_line: bool = False
split_number: int | None         # 3–30
intervals: list[float]           # bound values for coloured arcs
interval_colors: list[HexColor]  # one per interval
font_size: int | None            # 10–20
animation: bool = True
```

**`funnel`**
```
label_type: none | value | percent | category | category_value | value_percent | all = value
tooltip_label_type: (same set)
show_labels: bool = True
show_tooltip_labels: bool = True
```

**`radar`**
```
shape: polygon | circle = polygon
label_type: value | category_value = value
label_position: str | None       # one of ECharts' label positions
metric_bounds: dict[FieldName, {min: float|None, max: float|None}]  # per-metric axis bounds
```

**`treemap`**
```
show_labels: bool = True
show_upper_labels: bool = False   # labels on parent nodes
label_type: key | value | key_value = key
```

**`number`** (BigNumber)
```
subheader: str | None
subtitle: str | None
header_font_size: int | None
subheader_font_size: int | None
```

`table` has no `type_options` in A2 (conditional formatting / cell bars / pagination →
slice D).

---

## Implementation

### Backend — `backend/app/schemas/chart.py`
- Rewrite `ChartOptions`: nest `legend`, `labels`, `tooltip` as sub-models; extend
  `NumberFormat` with `prefix`/`suffix`; add `date_format`; add `type_options`.
- New per-family Pydantic models (`CartesianOptions`, `PieOptions`, `GaugeOptions`,
  `FunnelOptions`, `RadarOptions`, `TreemapOptions`, `NumberOptions`) under a
  `TypeOptions` container with optional fields per family.
- Remove the legacy flat fields (`stacked`, `percent`, `y_min`, `y_max`, `log_scale`,
  `x_axis_label`, `y_axis_label`, `data_labels`, `legend_position`, `show_legend`).
- Bump `CHART_SPEC_VERSION = "2"`.
- Validation: ranges (font sizes 10–20, split_number 3–30, opacity 0–1, radii 0–100),
  `interval_colors` length matches `intervals`, hex colours, bounded strings.

### Contract mirror — `frontend/src/types/api.ts`
- Mirror the full v2 `ChartOptions` + `TypeOptions` shape field-for-field (snake_case).

### Renderer — `frontend/src/components/chart/ChartRenderer.tsx`
- Read shared chrome (legend/labels/tooltip/number_format/date_format) + the relevant
  `type_options.<family>` in each branch.
- Implement the new behaviours: percent (100%) stacking, only-total label,
  label threshold/type/template/position, area opacity, markers/size, smooth,
  x-label rotation/interval, minor ticks/split-line, data-zoom (registers
  `DataZoomComponent`), tooltip mode/sort/total/percentage/time-format, pie
  radius/rose/labels-outside/label-line/total/Other-grouping, gauge
  angles/pointer/progress/round-cap/ticks/split/intervals+colors/font/animation,
  funnel label & tooltip types, radar shape/label/per-metric bounds, treemap
  upper-labels & label type.
- `NumberRenderer` reads `type_options.number` (subheader/subtitle/font sizes).
- Register any newly required ECharts components (e.g. `DataZoomComponent`).

### Builder — `frontend/src/pages/Builder.tsx` + a new `FormatControls` structure
- Replace the single flat `FormatControls` with a **type-aware** panel: a
  `FAMILY_FOR_TYPE: Record<ChartType, Family>` registry decides which family section to
  render alongside the shared sections.
- Split into composable sub-panels: `SharedFormatControls` (legend/labels/tooltip/
  number/colour) + one component per family (`CartesianControls`, `PieControls`, …).
- `toChartOptions` / `fromChartOptions` build & restore the nested v2 shape;
  `loadSpec` restores `type_options` for the loaded type's family.

---

## Testing (definition of done)

**Backend (pytest + ruff + mypy):**
- v2 `ChartOptions`/`TypeOptions` round-trip (rewrite `test_chart_spec.py`).
- Validation: rejects out-of-range font size / split_number / opacity / radius,
  mismatched `interval_colors` length, bad hex, unknown enum values.
- `CHART_SPEC_VERSION == "2"`.

**Frontend (Vitest + RTL + tsc + eslint):**
- `buildEChartsOption` honours each new option per type (table-driven per family):
  percent stacking, area opacity, markers, smooth, label type/threshold, pie radius/
  rose/Other-grouping, gauge intervals+colors/angles, funnel/radar/treemap label
  options, tooltip mode/total/percentage.
- `FormatControls` renders exactly the shared + correct family section for each of the
  14 types (no cross-family leakage).
- `toChartOptions`/`fromChartOptions`/`loadSpec` round-trip the nested shape.

**Docs:** rewrite the options section of `docs/CHART_SPEC.md` for v2; note the v1→v2
break and that v1 specs are not migrated.

---

## Dropped from Superset (approved)

- **D3 raw format-string editor** — superseded by the structured `number_format`
  plus `prefix`/`suffix` and `date_format`.
- **Stream-graph stack style**, **color-by-axis**, **forceCategorical / numerical-x
  truncation & bounds** — Superset-internal or not meaningful with our categorical-x
  ECharts mapping.
- **BigNumber trend line** — a new viz capability → **slice D**.
- **Table conditional formatting / cell bars / pagination** — heavier table work →
  **slice D**.

## Out of scope (later slices)
- New viz types and the table-formatting suite → **slice D**.
- Native filters, drill → **slice C**. Dashboard layout → **slice B**.
