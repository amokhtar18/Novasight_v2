# Chart-spec contract

> The declarative shape that describes one chart. **One spec, two producers, one
> renderer.** Manual configuration (the explore view / low-code builder) and the AI
> `NL→chart` endpoint both emit this exact shape, so they share a single renderer.

The spec is the seam between *deciding what a chart is* and *drawing it*. Nothing in
the spec mentions ECharts; the frontend renderer translates it into an ECharts
option. Nothing in the spec is SQL; the `query` describes a structured aggregation
that the query service compiles to a safe, read-only `SELECT`.

## Where it lives

| Side | File | Notes |
| --- | --- | --- |
| Backend | [`backend/app/schemas/chart.py`](../backend/app/schemas/chart.py) | Pydantic v2; the source of truth |
| Frontend | [`frontend/src/types/api.ts`](../frontend/src/types/api.ts) | TypeScript mirror |
| Example | [`docs/examples/chart-spec.example.json`](examples/chart-spec.example.json) | Canonical fixture used by both round-trip tests |

Field names are **snake_case on both sides**, so the JSON that crosses the wire is
identical — a backend-produced spec deserialises on the frontend and vice versa,
with no key translation. The round-trip is enforced by tests on both sides
([`backend/tests/test_chart_spec.py`](../backend/tests/test_chart_spec.py) and
[`frontend/src/test/chartSpec.test.ts`](../frontend/src/test/chartSpec.test.ts)),
both reading the one canonical fixture so the two languages cannot drift.

## Shape

See [`docs/examples/chart-spec.example.json`](examples/chart-spec.example.json) for
the canonical v2 fixture used by both the backend and frontend round-trip tests.

A condensed sketch:

```jsonc
{
  "version": "2",                // contract version — "2" for all new specs
  "type": "bar",                 // bar | line | area | pie | table | number | ...
  "query": {                     // WHERE the data comes from (≥1 source required)
    "dataset_id": "…uuid…",      //   dataset the inline query runs against
    "query": { /* QueryRequest */ }, //   structured aggregation (Phase 1 path)
    "metric_refs": [],           //   OR governed metric names (semantic / AI path)
    "dimensions": [],            //   plain dimensions to group by (semantic path)
    "time_dimensions": []        //   optional time-dimension rollups (semantic path)
  },
  "encoding": {                  // HOW columns map to visual channels
    "x": "month",                //   category axis (x / pie label); omit for table
    "series": [                  //   value series (≥1); for a table, the columns
      { "field": "sales", "name": "Sales", "color": "#3b82f6" }
    ],
    "breakdown": []              //   dimensions pivoted into one series each (optional)
  },
  "options": {                   // display-only v2 structure; never affects the query
    "title": "Monthly sales",
    "color_scheme": null,        //   named palette key or null for theme default
    "palette": [],               //   explicit hex list — overrides color_scheme
    "legend": { "show": true, "position": "top", "sort": "none" },
    "labels": { "show": false, "template": null, "threshold": null },
    "tooltip": { "mode": "axis", "sort_by_metric": false },
    "type_options": {            //   per-family options (cartesian / pie / gauge / …)
      "cartesian": { "stacked": false, "y_axis_label": "Amount" }
    }
  }
}
```

> **v1 → v2 break:** the v1 flat fields (`stacked`, `show_legend`, `x_axis_label`,
> `y_axis_label`) no longer exist in `ChartOptions`. Use `type_options.cartesian` and
> `legend.show` instead. See the [v2 section below](#options-v2) for the full field
> reference.

### `type`

`bar`, `line`, `area`, `pie`, `table`, `number`, `scatter`. `area` renders as a line
series with an area fill. `table` presents the query result as columns. `number` is a
single "big number" KPI tile that shows the **total of its first series** across the
result (a single-aggregate query shows that value; a grouped query shows the grand
total). `scatter` plots each series' values against a **numeric `x`** (a value axis,
not categories) as `[x, y]` points. `table` and `number` are the two types that may
omit `encoding.x`; `scatter`, like the other axis charts, requires it.

### `query` — query/metric refs

A chart must be **grounded**: it references a data source, never raw SQL. At least
one of two sources is required:

- an inline structured `query` (a [`QueryRequest`](../backend/app/schemas/query.py))
  against `dataset_id` — the structured-aggregation path used today; and/or
- `metric_refs` — names of governed metrics resolved by the semantic layer, the
  path the AI layer will use (see the `nl-to-sql-grounding` skill).

There is intentionally nowhere to put a raw SQL string.

For the semantic path, `dimensions` lists the plain (non-time) governed dimensions to
group by. The first is the category axis (`encoding.x`); any others are **breakdown**
dimensions. `time_dimensions` (a list of
[`SemanticTimeDimension`](../backend/app/schemas/semantic.py): `{ dimension, granularity }`)
carries any time-dimension rollup on the spec, so a saved or AI-generated chart
re-runs at the same granularity. The rolled-up column key is
`<dimension>.<granularity>` and is the value `encoding.x` reads — re-run logic
(`frontend/src/lib/useChartData.ts`) sends `dimensions` as Cube `dimensions` and the
time rollup as `timeDimensions`. Legacy single-dimension specs leave `dimensions`
empty and carry their one dimension on `encoding.x` alone (re-run falls back to it).
See `docs/SEMANTIC_LAYER.md` for the query semantics.

#### Optional governed query parameters on `ChartQuery`

Three optional fields let a saved or AI-generated chart re-run with the same
constraints it was created with:

- **`filters`** (`list[SemanticFilter]`, default `[]`) — governed filter predicates
  of the form `{ member, operator, values }`. Each `member` is a fully-qualified
  Cube identifier (e.g. `sales.region`). `operator` is one of the closed set:
  `equals`, `notEquals`, `contains`, `notContains`, `gt`, `gte`, `lt`, `lte`,
  `set`, `notSet`. Presence-check operators (`set`/`notSet`) take no values; all
  others require at least one. Every member is **re-validated against the governed
  allow-list** by the semantic service before any Cube call (golden rule #3 — no
  filter is a way to reach an ungoverned field).

- **`order`** (`dict[SemanticRef, OrderDir]`, default `{}`) — server-side ordering,
  e.g. `{"sales.total": "desc"}`. Keys must be members selected by the query
  (`metric_refs`, `dimensions`, or a time dimension's resolved key); the service
  rejects any key that is not in the query's governed scope.

- **`limit`** (`int | null`, default `null`) — optional per-chart row cap (`ge=1`).
  The semantic service clamps this to `settings.max_query_rows` so no caller can
  exceed the platform limit, regardless of what the spec carries.

`time_dimensions[].date_range` accepts either a **relative token** from the closed
set (`last_7_days`, `last_30_days`, `last_90_days`, `this_month`, `last_month`,
`this_quarter`, `last_quarter`, `this_year`, `last_year`) or an **absolute
`[from, to]` pair** of ISO-date strings (e.g. `["2024-01-01", "2024-03-31"]`). The
service translates relative tokens to Cube's native relative-range strings before
forwarding the query.

### `encoding` — encodings

`x` names the column used for the category axis (or pie slice labels). `series` is a
non-empty list; each entry's `field` is a column name in the resulting
`QueryResponse`. `name` is the legend label (defaults to `field`); `color` is an
optional explicit colour.

`breakdown` lists dimension columns whose values are **pivoted into one series each**
at render time (`frontend/src/lib/chartPivot.ts`): a chart with one measure grouped by
a category dimension *and* a breakdown dimension becomes a grouped/stacked chart with
one series per breakdown value. When `breakdown` is set, `series[0]` is the measure
that supplies the pivoted values; pivoting applies only to multi-series category types
(bar/hbar/line/area/combo/radar). The drag-and-drop builder's X-axis / Breakdown /
Metrics shelves map directly onto `encoding.x` / `encoding.breakdown` / `series`.

Encoding `field`/`x` values are *display references* only — they are pattern-bounded
(`^[A-Za-z_][A-Za-z0-9_.]*$`) and never reach the SQL builder.

### `options` (v2)

Display-only. Changing any option never changes the query or the data.

#### v1 → v2 BREAK

The v1 flat fields (`stacked`, `show_legend`, `legend_position`, `data_labels`,
`log_scale`, `y_min`, `y_max`) **have been removed**. They do not exist in the
`ChartOptions` TypeScript type or the backend Pydantic model. Saved specs that carry
those flat fields are **not migrated** — they render with the v2 defaults. Any new
spec must use the v2 structure documented below.

#### Shared chrome — present on every chart type

| Field | Type | Notes |
| --- | --- | --- |
| `title` | `string \| null` | Override the auto-generated title. `null` keeps the auto title. |
| `color_scheme` | `string \| null` | Named palette (e.g. `"blues"`, `"vivid"`). `null` uses the theme default. |
| `palette` | `string[]` | Explicit hex colour list — overrides `color_scheme`. |
| `sort` | `ChartSort` | `"none"` \| `"value_desc"` \| `"value_asc"` \| `"label_asc"` \| `"label_desc"`. |
| `date_format` | `string \| null` | strftime-style format applied to time-axis labels (e.g. `"YYYY-MM-DD"`). |

**`legend`** (`LegendOptions`):

| Field | Type | Default |
| --- | --- | --- |
| `show` | `boolean` | `true` |
| `position` | `"top"` \| `"bottom"` \| `"left"` \| `"right"` | `"top"` |
| `type` | `"plain"` \| `"scroll"` | `"plain"` |
| `margin` | `number \| null` | ECharts default |
| `sort` | `"none"` \| `"asc"` \| `"desc"` | `"none"` |

**`number_format`** (`NumberFormat`):

| Field | Type | Notes |
| --- | --- | --- |
| `style` | `"plain"` \| `"currency"` \| `"percent"` | Default `"plain"`. |
| `decimals` | `number \| null` | Fixed decimal places. `null` = auto. |
| `compact` | `boolean` | Compact notation (`1.2k`, `3.4M`). |
| `currency` | `string \| null` | ISO currency code (e.g. `"USD"`). Only used when `style="currency"`. |
| `prefix` | `string \| null` | Literal string prepended to the formatted value. |
| `suffix` | `string \| null` | Literal string appended to the formatted value. |

**`labels`** (`LabelOptions`) — data-label overlays on the chart marks:

| Field | Type | Notes |
| --- | --- | --- |
| `show` | `boolean` | Default `false`. |
| `position` | `string \| null` | ECharts label position string (e.g. `"top"`, `"inside"`). |
| `template` | `string \| null` | ECharts formatter template (e.g. `"{c}%"`). |
| `threshold` | `number \| null` | Minimum value to show a label for. |

**`tooltip`** (`TooltipOptions`):

| Field | Type | Notes |
| --- | --- | --- |
| `mode` | `"item"` \| `"axis"` \| `"rich"` | Default `"axis"`. |
| `sort_by_metric` | `boolean` | Sort tooltip rows by metric value descending. |
| `show_total` | `boolean` | Show the sum row in stacked-series tooltips. |
| `show_percentage` | `boolean` | Show each series' share of the total. |
| `time_format` | `string \| null` | Format string for time-axis tooltips. |

#### Per-family options — `type_options`

Only the key matching the chart's family is populated; all others are absent/null.
The family is determined by the chart type:

| `ChartType` | Family key |
| --- | --- |
| `bar`, `hbar`, `line`, `area`, `combo`, `scatter` | `cartesian` |
| `pie`, `donut` | `pie` |
| `gauge` | `gauge` |
| `funnel` | `funnel` |
| `radar` | `radar` |
| `treemap` | `treemap` |
| `heatmap` | `heatmap` |
| `sankey` | `sankey` |
| `number` | `number` |
| `table` | *(no per-family options)* |

**`type_options.cartesian`** (`CartesianOptions`):

`stacked`, `percent`, `only_total`, `label_threshold`, `area_opacity`, `markers`,
`marker_size`, `smooth`, `x_axis_label`, `y_axis_label`, `x_label_rotation`
(`0 | 45 | 90`), `x_label_interval` (`"auto" | "all"`), `y_min`, `y_max`,
`log_scale`, `minor_ticks`, `minor_split_line`, `data_zoom`,
`sort_series` (`"none" | "asc" | "desc"`).

**`type_options.pie`** (`PieOptions`):

`label_type` (`"category" | "value" | "percent" | "category_value" | "value_percent" | "category_value_percent"`),
`inner_radius`, `outer_radius`, `rose_type` (`"none" | "area" | "radius"`),
`labels_outside`, `label_line`, `show_total`, `show_labels_threshold`,
`group_others_threshold`.

**`type_options.gauge`** (`GaugeOptions`):

`min`, `max`, `start_angle`, `end_angle`, `show_pointer`, `show_progress`
(default **false** — was implicitly enabled in v1 specs; matches Superset default),
`round_cap`, `show_axis_tick`, `show_split_line`, `split_number`, `intervals`,
`interval_colors`, `font_size`, `animation`.

**`type_options.funnel`** (`FunnelOptions`):

`label_type`, `tooltip_label_type`, `show_labels`, `show_tooltip_labels`.

**`type_options.radar`** (`RadarOptions`):

`shape` (`"polygon" | "circle"`), `label_type` (`"value" | "category_value"`),
`label_position`, `metric_bounds` — a `Record<string, { min?, max? }>` keyed
by **x-category name** (the dimension value, e.g. `"Sales"`, not the field path).

**`type_options.treemap`** (`TreemapOptions`):

`show_labels`, `show_upper_labels`,
`label_type` (`"key" | "value" | "key_value"`).

**`type_options.number`** (`NumberOptions`) — KPI tile extras:

`subheader`, `subtitle`, `header_font_size`, `subheader_font_size`.

### heatmap / sankey (2-dimension × 1-measure)

Both read **two governed dimensions and one measure**: dimension 1 → `encoding.x`,
dimension 2 → `encoding.breakdown[0]`, measure → `encoding.series[0].field`
(`query.dimensions = [dim1, dim2]`, `query.metric_refs = [measure]`). The spec
validator rejects either type without `x`, without a `breakdown` entry, or with
more than one series.

- **heatmap** — a density matrix; the measure colours each x×y cell via a `visualMap`.
  Options (`type_options.heatmap`): `show_values`, `min_color`/`max_color`,
  `value_min`/`value_max` (manual scale), `show_visual_map`, `cell_border`.
- **sankey** — a flow diagram; links go from each x value to each y value weighted by
  the measure. Options (`type_options.sankey`): `orient`, `node_align`, `node_width`,
  `node_gap`, `link_color`, `show_labels`.

## Validation invariants

The Pydantic schema enforces (and the frontend type mirrors):

- a `ChartQuery` must have an inline `query` **or** at least one `metric_refs` entry;
- `encoding.series` has at least one entry;
- `encoding.x` is required for every type except `table`, `number`, and `gauge`;
- `heatmap` and `sankey` additionally require `encoding.x`, a non-empty `encoding.breakdown`, and exactly one series;
- `field`/`x`/`metric_refs` match the bounded field-name pattern above.

## Round-trip guarantee

The acceptance test for this contract is that a spec round-trips backend↔frontend.
Concretely:

1. the backend parses the canonical fixture into a `ChartSpec` and re-serialises it
   to value-identical JSON, and
2. the frontend reads the *same* file, finds it assignable to the TS `ChartSpec`,
   round-trips it through JSON unchanged, and feeds it to the shared renderer.

Run both: `cd backend && uv run pytest tests/test_chart_spec.py` and
`cd frontend && pnpm test chartSpec`.
