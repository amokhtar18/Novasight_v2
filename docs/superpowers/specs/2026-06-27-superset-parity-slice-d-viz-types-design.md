# Superset-parity for charts & dashboards — Slice D: More viz types (heatmap + sankey)

**Date:** 2026-06-27
**Status:** Design approved; ready for implementation plan
**Depends on:** Slice A (query-filter primitives: `SemanticFilter`, multi-dimension query), Slice A2 (`ChartSpec` v2 + `TypeOptions`), Slice C (native filters, cross-filter overlay, drill modals)
**Branch:** will get its own feature branch

---

## Program context

Fourth slice of the Superset-parity program (see
`2026-06-26-superset-parity-slice-a-builder-design.md` for the program overview and
golden-rule constraints). Sequence:

| Slice | Theme | Status |
|-------|-------|--------|
| A | Chart-builder (Explore) parity — query shaping + chart actions | done |
| A2 | Per-type formatting parity — Superset "Customize" panel | done |
| C | Native filters — typed panel, per-tile scoping, cascading, drill | done |
| **D** | **More viz types — heatmap + sankey (full interactivity)** | **this spec** |
| B | Dashboard layout — resize, rows/columns, tabs, header, fullscreen | later |

The program originally framed D as a broad "more viz types & options" bucket. This cycle
deliberately scopes it to **two** new types — **heatmap** and **sankey** — taken
end-to-end with full interactivity, per golden rule #4 (ship thin vertical slices). Both
are two-dimension × one-measure visualizations, so they share one encoding shape and one
interaction story. Other candidates (sunburst, waterfall, bubble, big-number-with-trend)
are explicit follow-ups.

---

## Goal

Add **heatmap** and **sankey** as first-class chart types that work everywhere the
existing 14 types do — the builder, the shared `ChartRenderer`, saved charts, and
dashboard tiles — and that participate **fully** in dashboard interactivity:

- **Heatmap** — a density matrix: x dimension × y dimension, one measure mapped to cell
  colour via an ECharts `visualMap`.
- **Sankey** — a flow diagram: links from an x (source) dimension value to a y (target)
  dimension value, one measure as the flow weight.
- **Cross-filter** — clicking a heatmap **cell** cross-filters the dashboard on **both**
  axes (x AND y); clicking a sankey **node** cross-filters on that node's dimension.
- **Drill** — drill-by and drill-to-detail are made aware of the two encoded dimensions
  so re-pivot / breakdown options exclude both.

Everything stays grounded on the governed semantic layer: both types are pure ECharts
options over a structured semantic query (measures aggregated by dimensions). No raw SQL,
no new physical-table access, no new configuration (golden rules #1 and #3 untouched).

---

## Approach decision: encoding the two dimensions

**Chosen — reuse existing channels.** `encoding.x` = dimension 1, `encoding.breakdown[0]`
= dimension 2, `series[0].field` = the measure. The query carries
`dimensions=[dim1, dim2]` + `metric_refs=[measure]`, which the builder's existing
multi-dimension drag flow already produces and the semantic service already validates.
The renderer interprets `breakdown[0]` as the secondary axis (heatmap Y / sankey target)
**only** for these two types. No `ChartSpec.encoding` schema change.

**Rejected — explicit `encoding.y` channel.** Clearer intent, but a schema addition +
builder rework + migration story for something the reuse approach already expresses.
Gold-plating (golden rule #4).

---

## Current state (what already exists)

- **`ChartType`** (`backend/app/schemas/chart.py`) — 14 types; per-family option models
  (`CartesianOptions`, `PieOptions`, `GaugeOptions`, `FunnelOptions`, `RadarOptions`,
  `TreemapOptions`, `NumberOptions`) aggregated in `TypeOptions`; a validator
  (`_require_x_for_axis_charts`) that exempts only `table`/`number`/`gauge` from needing
  `encoding.x`.
- **Multi-dimension query** — `ChartQuery.dimensions` + `ChartEncoding.breakdown` already
  let a chart group by two dimensions; the builder's drag flow puts the first dimension on
  `x` and the rest on `breakdown`.
- **`ChartRenderer.tsx`** — a `buildOption(spec)` function with one `if (spec.type === …)`
  branch per ECharts type; `table`/`number` render via `TableRenderer`/`NumberRenderer`.
- **Cross-filter** — `DashboardDetail` holds a single `crossFilter: SemanticFilter | null`
  overlay; `DashboardCardTile` calls `onCrossFilter(member, value)` from a clicked
  category; `resolveTileFilters` merges the single overlay per tile (cube-compatible only).
- **Drill** — `DrillByModal` (`buildDrillBySpec`) and `DrillToDetailModal`
  (`buildDetailRequest`) exclude `query.dimensions ∪ encoding.x` from their
  re-pivot/remaining-dimension options and focus on an x-value.

---

## Design

### 1. Backend — `schemas/chart.py`

- Add `"heatmap"`, `"sankey"` to `ChartType`.
- `HeatmapOptions` (lean): `show_values: bool = False`, `min_color: HexColor | None`,
  `max_color: HexColor | None`, `value_min: float | None`, `value_max: float | None`
  (manual `visualMap` scale; auto when unset), `show_visual_map: bool = True`,
  `cell_border: bool = False`.
- `SankeyOptions` (lean): `orient: Literal["horizontal","vertical"] = "horizontal"`,
  `node_align: Literal["left","right","justify"] = "justify"`,
  `node_width: int | None` (1–100), `node_gap: int | None` (1–100),
  `link_color: Literal["source","target","gradient"] = "gradient"`,
  `show_labels: bool = True`.
- Add `heatmap: HeatmapOptions | None` and `sankey: SankeyOptions | None` to `TypeOptions`.
- New validator: for `heatmap`/`sankey`, require `encoding.x` **and** non-empty
  `encoding.breakdown` **and** exactly one `encoding.series` entry (the measure). These
  types stay outside the no-x exemption set.
- `CHART_SPEC_VERSION` stays `"2"` (additive, non-breaking).

### 2. Frontend — `types/api.ts` + `ChartRenderer.tsx`

- Mirror the two `ChartType` strings and the `HeatmapOptions`/`SankeyOptions` interfaces in
  `TypeOptions`.
- `buildHeatmapOption(spec, data)`: ECharts `heatmap` series + `visualMap`. `xAxis.data` =
  distinct values of the `encoding.x` column; `yAxis.data` = distinct values of the
  `breakdown[0]` column; series `data` = `[xIndex, yIndex, measureValue]`. `visualMap`
  min/max from options or auto from the data; `min_color`/`max_color` set the gradient;
  `show_values` toggles cell labels; honours the shared `number_format`.
- `buildSankeyOption(spec, data)`: ECharts `sankey` series. `data` (nodes) = distinct x
  values ∪ distinct y values (deduped; x and y namespaces are disjoint by construction —
  if a value appears in both, suffix the node id to keep links acyclic); `links` =
  `{ source: xVal, target: yVal, value: measureValue }`; `orient`/`nodeAlign`/`nodeWidth`/
  `nodeGap`/label + link colour from `SankeyOptions`.
- Add both to `CHART_TYPES` in `SemanticQueryBuilder.tsx`; neither is in `NO_X_TYPES`.

### 3. Builder UX — `SemanticQueryBuilder.tsx` / `Builder.tsx`

- Reuse the existing 2-dimension + 1-measure drag flow. Relabel the encoding slots
  contextually: heatmap → "X" / "Y", sankey → "Source" / "Target". Show an inline hint when
  the selected type needs exactly two dimensions and one measure, and surface the
  validator's message if the user previews an incomplete spec.

### 4. Cross-filter — widen the overlay to a list

- Generalize `crossFilter` from `SemanticFilter | null` to `SemanticFilter[]` (empty =
  none) across `DashboardDetail`, `DashboardGrid`, `DashboardCardTile`, and
  `resolveTileFilters` (which merges the list, cube-compatible entries only).
- Generalize the click callback to `onCrossFilter(pairs: { member: string; value: string }[])`:
  - cartesian/pie → one pair (behaviour unchanged);
  - heatmap cell → two pairs (x member+value, y member+value);
  - sankey node → one pair (the node's dimension member + value).
- `ChartRenderer` click handlers map ECharts click params to those pairs; the transient
  overlay still clears on "clear all" and is suppressed in edit mode (as today).

### 5. Drill — two-dimension aware

- `buildDrillBySpec` / `buildDetailRequest` exclude **both** encoded dims
  (`encoding.x` ∪ `encoding.breakdown` ∪ `query.dimensions`) from re-pivot / remaining
  options, so a heatmap/sankey never offers to re-pivot by an already-shown axis.
- Focus stays on the **x** dimension for these types (keeps the modals bounded and reuses
  the existing focus selector); the grounded re-query path is otherwise unchanged.

### 6. Testing (definition of done)

- **Backend** (`test_chart_spec.py`): heatmap/sankey spec round-trip; the new validator
  (rejects missing `breakdown`, rejects >1 series, requires `x`).
- **Frontend** (`chartRenderer.test.ts`): heatmap builds `visualMap` + `[x,y,v]` data and
  honours `show_values`/colours; sankey builds nodes + links with the right orient/align.
  Cross-filter emission: a heatmap cell yields **two** pairs, a sankey node **one**; the
  widened `SemanticFilter[]` overlay flows through `resolveTileFilters`
  (`dashboardCardTile.test.tsx` / `dashboardDetailFilters.test.tsx`). Drill exclusion:
  both encoded dims removed for these types (`drillByModal`/`drillToDetailModal` tests).
- **Docs**: `docs/CHART_SPEC.md` (the two types + their options); a heatmap/sankey
  cross-filter note in `docs/DASHBOARDS.md`.

### 7. Golden-rule posture

- **#1 (no hardcoded config):** no new settings; nothing environment/tenant-specific.
- **#3 (grounded AI/queries):** both types are display layers over the existing structured
  `/semantic/query`; no SQL, no new physical access. Cross-filter and drill reuse the
  governed `SemanticFilter` / semantic-query paths.
- **#4 (thin slices):** two types, one shared encoding + interaction story.
- **#5 (tested + typed + documented):** tests, `ruff`+`mypy` / `tsc`+`eslint`, and the two
  docs above.

---

## Out of scope / follow-ups

- Other viz types from the original D bucket: **sunburst, waterfall, bubble,
  big-number-with-trend, box plot, pivot table, conditional table formatting,
  annotations**. (Box plot needs distribution quantiles the aggregate semantic layer does
  not expose — a separate data-shaping problem.)
- **Cell-level (x+y) drill focus** for heatmap — drill focus stays on x for this slice.
- **Geo / map** types (need geo data + a tile layer).

## Open items to decide during build

- Heatmap default colour gradient (theme-derived vs a fixed two-stop default) — pick a
  sensible default in the renderer, overridable via `min_color`/`max_color`.
- Sankey node-id disambiguation when an x value and a y value share a string — confirm the
  suffix scheme keeps links readable and acyclic.
