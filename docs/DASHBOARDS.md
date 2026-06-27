# Dashboard native filters

> Slice C replaces the old single-filter bar and the `filter` decoration tile kind with
> a first-class **native filter** subsystem. Native filters are configured per dashboard,
> scoped per tile, and resolve entirely through the governed semantic layer — no raw SQL,
> no client-supplied field names that bypass the allow-list (golden rule #3).

## Where it lives

| Side | File | Notes |
| --- | --- | --- |
| Backend schema | [`backend/app/schemas/dashboard.py`](../backend/app/schemas/dashboard.py) | `NativeFilter`, `FilterScope`, `NumericRange` — Pydantic v2 source of truth |
| Frontend resolution | [`frontend/src/lib/dashboardFilters.ts`](../frontend/src/lib/dashboardFilters.ts) | `resolveTileFilters`, `filterAppliesToTile`, `defaultSelection`, `cubeOf` |
| Values endpoint | [`backend/app/api/v1/semantic.py`](../backend/app/api/v1/semantic.py) | `POST /semantic/values` |
| Drill by | [`frontend/src/components/chart/DrillByModal.tsx`](../frontend/src/components/chart/DrillByModal.tsx) | Re-pivot by another governed dimension |
| Drill to detail | [`frontend/src/components/chart/DrillToDetailModal.tsx`](../frontend/src/components/chart/DrillToDetailModal.tsx) | Grounded breakdown by remaining governed dimensions |

## `NativeFilter` — persisted config shape

A dashboard's `native_filters` list (persisted in `DashboardRead.native_filters`, updated
via `PATCH /dashboards/{id}`) holds the **configured** state of each filter — its default
selection only. The **live selection** is client session state seeded from the config's
default when the dashboard first loads.

```jsonc
{
  "id": "region_filter",           // unique within the dashboard; 1–64 chars
  "kind": "value",                 // "value" | "time" | "numeric"
  "member": "sales.region",        // governed SemanticRef (cube.member)
  "label": "Region",               // display label; null uses member name
  "operator": "equals",            // value filters: equals|notEquals|contains|notContains
  "default_values": ["West"],      // value filter default; seeded into session state
  "date_range": null,              // time filter default: relative token or [from, to]
  "numeric_range": { "min": 0, "max": 1000 }, // numeric filter default
  "scope": { "mode": "auto", "tile_ids": [] }, // see Scoping below
  "parent_id": null,               // cascading parent filter id (or null)
  "required": false                // marks filter as mandatory for viewers
}
```

`member` must be a `SemanticRef` — the pattern `^[A-Za-z_][A-Za-z0-9_.]*$` is checked
at the boundary and then re-validated against the governed allow-list when a tile runs.
Persisting a filter never widens data access.

A dashboard may have up to 20 native filters (`max_length=20` on `DashboardUpdate.native_filters`).

## Filter kinds and resolution to semantic primitives

`resolveTileFilters` in `dashboardFilters.ts` converts each applicable filter's live
selection into the Slice-A semantic primitives (`SemanticFilter[]` and a
`dateRanges` map) that `buildSemanticRequest` / `useChartData` accepts.

### value

A `value` filter resolves to one `SemanticFilter`:

```ts
{ member: f.member, operator: f.operator ?? "equals", values: sel.values }
```

Allowed operators are a closed set: `equals`, `notEquals`, `contains`, `notContains`.
The backend rejects any other operator at persist time.

### numeric

A `numeric` filter resolves to up to **two** `SemanticFilter` entries — one for the lower
bound and one for the upper bound (either side optional):

```ts
// min is present:
{ member: f.member, operator: "gte", values: [String(sel.min)] }
// max is present:
{ member: f.member, operator: "lte", values: [String(sel.max)] }
```

`NumericRange.min` must not exceed `max` (enforced by the backend `@model_validator`).

### time

A `time` filter resolves to a `date_range` entry in the `dateRanges` map keyed by the
filter's `member`. The value is either a `RelativeDateRange` token
(`last_7_days` | `last_30_days` | `last_90_days` | `this_month` | `last_month` |
`this_quarter` | `last_quarter` | `this_year` | `last_year`) or an absolute
`[from, to]` pair of ISO-date strings (e.g. `["2024-01-01", "2024-03-31"]`). At view
time `buildSemanticRequest` (in `useChartData`) injects this onto the matching time
dimension before the request is sent, replacing any `date_range` already on that
dimension in the tile's spec; the semantic service then forwards it to Cube as a
`dateRange`.

## Scoping

`FilterScope` controls which tiles a filter targets:

```jsonc
{ "mode": "auto", "tile_ids": [] }   // auto: all cube-compatible tiles
{ "mode": "tiles", "tile_ids": ["<uuid>", ...] }  // explicit allowlist
```

**Cube-compatibility safety rule** (always enforced, regardless of `mode`): a filter
only applies to a tile whose set of cubes (derived from `tile.chart.spec.query.metric_refs`)
contains the filter's member's cube. This prevents a filter from breaking an
unrelated tile that does not know the filtered member. See `filterAppliesToTile` in
`dashboardFilters.ts`:

```ts
const cube = cubeOf(f.member);          // "sales" from "sales.region"
if (!cube || !tileCubes(tile).has(cube)) return false;
```

In `tiles` mode the tile's id must additionally appear in `scope.tile_ids`.

Only `chart` tiles are eligible; decoration tiles (`text`, `markdown`, `image`,
`divider`) are never filtered.

## Cascading

A filter can declare another filter as its `parent_id`. The child filter's value
dropdown passes the parent's live selection as `constraints` to `POST /semantic/values`,
narrowing the available choices to values that coexist with the parent's selection
(server-side cascading join via the Cube query).

The backend enforces three rules at `PATCH /dashboards/{id}` time:

1. **Parent must be a value filter** — only `kind: "value"` filters may be referenced
   as a `parent_id`.
2. **No cycles** — the parent chain is walked and any loop raises a validation error.
3. **Unique ids** — `native_filters` ids must be distinct within the dashboard.

A filter cannot reference itself as its own parent (`parent_id != id` is enforced
at the `NativeFilter` level).

## `POST /semantic/values` — grounded filter dropdown values

```
POST /semantic/values
```

Returns the distinct values for a governed dimension, used to populate filter
dropdowns (and for cascading child constraints).

**Request** (`SemanticValuesRequest`):

| Field | Type | Notes |
| --- | --- | --- |
| `member` | `SemanticRef` | The governed dimension to fetch values for |
| `search` | `string \| null` | Optional substring for server-side typeahead |
| `constraints` | `SemanticFilter[]` | Parent-filter selections (cascading); max 20 |
| `limit` | `int \| null` | Requested row cap; clamped to `settings.max_filter_values` |

**Response** (`SemanticValuesResponse`):

```jsonc
{ "values": ["East", "West", "North", "South"] }
```

The endpoint is fully tenant-scoped and fail-closed: `member` and every member in
`constraints` are re-validated against the governed allow-list before any Cube call.
Invalid members return `422`; a temporarily unavailable semantic layer returns `503`.

## Drill-by

**Drill-by** lets a user re-pivot an existing chart by another governed dimension of
the same cube, optionally focused on one data point.

`buildDrillBySpec` (in `DrillByModal.tsx`) builds a new `ChartSpec` from the base
spec: it carries `metric_refs` unchanged and replaces `dimensions`, `time_dimensions`,
`filters`, and `encoding` with the chosen `dimension` (plus any active tile filters
and an optional point filter). The spec is then re-run through `useChartData` — the
same grounded `/semantic/query` path the chart already uses. No backend change; no raw
SQL. If the base type is `number` or `table` (no category axis), the type is coerced
to `bar`.

The dimension picker is populated from the governed model's `dimensions` list for the
same cube, excluding the chart's current x axis — so only valid, governed choices are
ever offered.

## Drill-to-detail

**Drill-to-detail** provides a semantic breakdown of a clicked point across all
remaining governed dimensions of the same cube.

`buildDetailRequest` (in `DrillToDetailModal.tsx`) builds a `SemanticQueryRequest`
that queries the tile's `metric_refs` grouped by every governed dimension on the cube
that is not already encoded in the tile (`spec.query.dimensions` + `spec.encoding.x`).
Filters are the union of the spec's saved filters, the tile's active dashboard
filters, and an optional point filter for the focused x-value.

**This is not raw rows.** The result is a grounded metric query that travels through
the same validation and tenant-scoping as every other semantic query (golden rule #3).
The breakdown is rendered as a table (`TableRenderer`) inside a modal.

## Migration note

Slice C is a **fresh-start** change:

- The legacy **single-filter bar** (a global filter UI that lived above the grid) has
  been removed.
- The `filter` **decoration tile kind** (a slicer tile that appeared in the grid) has
  been removed from `TileKind`.

There is no data migration — existing dashboards that carried the old filter bar config
or `filter` tiles will render without them. No rows are dropped or transformed.

## Cross-filtering from chart clicks

Clicking a data point on a category-axis chart emits a cross-filter pair
`{ member, value }` that DashboardDetail overlays on the grid as a temporary
`SemanticFilter`. Only tiles whose cube contains the filtered member are affected.

Heatmap and sankey participate in cross-filtering: clicking a **heatmap cell** emits two
filters (its x value AND its y value); clicking a **sankey node** emits one filter on that
node's dimension. As with other charts, a cross-filter only applies to tiles whose cube
contains the filtered member. Only the most recently clicked chart's filter(s) form the cross-filter overlay — clicking a new point (or cell) replaces any prior overlay rather than accumulating across charts.

## Dashboard layout (free resizable grid)

Dashboards render on a **12-column gridstack grid**. Each tile stores its placement as
`x`, `y`, `w`, `h` (grid units, `w`/`h` ∈ [1,12]) — the same fields the
`PUT /dashboards/{id}/layout` endpoint persists; this slice added no backend change.

- **View mode** renders tiles static at their stored `x/y/w/h`.
- **Edit mode** enables drag-to-move (from the tile's grip handle) and drag-to-resize.
  A keyboard-accessible **Size** control on each tile sets width/height for users who
  cannot drag; full keyboard *drag* is a known gridstack limitation.
- **Persistence:** gridstack's `change` event maps to `{ id, x, y, w, h }` plus a
  row-major `position` (top-to-bottom, then left-to-right), applied optimistically and
  saved via the layout endpoint (debounced).
- **Responsive:** one 12-column layout is persisted; below ~768px the grid collapses
  toward a single column. That collapsed arrangement is not written back.
- **Integration:** gridstack lives entirely inside `DashboardGrid`; tile content
  (`DashboardCardTile`: charts, drill, cross-filter) is ordinary React. The mapping
  lives in `frontend/src/lib/dashboardLayout.ts` (`nodesToLayoutTiles`).

Not yet supported (follow-ups): tabs, nested row/column containers, per-tile styling,
fullscreen, per-breakpoint persisted layouts.
