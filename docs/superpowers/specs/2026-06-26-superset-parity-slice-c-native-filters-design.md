# Superset-parity for charts & dashboards — Slice C: Native filters

**Date:** 2026-06-26
**Status:** Design approved; ready for implementation plan
**Depends on:** Slice A (query-filter primitives: `SemanticFilter`, `date_range`), Slice A2 (`ChartSpec` v2)
**Branch:** will get its own feature branch

---

## Program context

Third slice of the Superset-parity program (see
`2026-06-26-superset-parity-slice-a-builder-design.md` for the program overview and
golden-rule constraints). Sequence:

| Slice | Theme | Status |
|-------|-------|--------|
| A | Chart-builder (Explore) parity — query shaping + chart actions | done |
| A2 | Per-type formatting parity — Superset "Customize" panel | done |
| **C** | **Native filters — typed panel, per-tile scoping, cascading, drill** | **this spec** |
| B | Dashboard layout — resize, rows/columns, tabs, header, fullscreen | later |
| D | More viz types & options — pivot, big-number trend, heatmap, box plot, conditional table formatting, annotations | later |

Slice C reuses the **query-filter primitives Slice A introduced** (`SemanticFilter`'s
10 operators, the `date_range` relative-token/absolute model on time dimensions), so it
is mostly a dashboard-level UI + scoping layer plus one new grounded backend endpoint.

This spec covers **all four** capabilities the program table assigns to Slice C in a
single cycle: the typed filter panel (value/time/numeric), per-tile scoping, cascading,
and drill-by/drill-to-detail.

---

## Goal

Bring NovaSight's dashboards to Superset-parity on **native filters** within the
semantic-layer-only model:

- **Typed filters** as first-class, configurable dashboard objects: **value**
  (governed dimension + selectable values), **time** (date range), **numeric** (range).
- **Per-tile scoping** — each filter declares which tiles it affects, replacing today's
  implicit cube-prefix heuristic.
- **Cascading** — a value filter's options can be constrained by a parent filter's
  current selection.
- **Drill-by** — pivot a chart by another governed dimension from a clicked point.
- **Drill-to-detail** — a grounded breakdown of a clicked point, re-interpreted to
  satisfy golden rule #3 (no raw physical rows).

Everything stays grounded on the governed semantic layer (Cube). Filter selections
resolve to the same primitives a saved chart already carries, so the existing per-tile
re-query path (`useChartData` → `/semantic/query`) does the work — the backend grows by
exactly one endpoint plus a richer dashboard persistence shape.

---

## Current state (what already exists)

- **Slice A primitives** — `SemanticFilter` (10 operators: equals/notEquals/contains/
  notContains/gt/gte/lt/lte/set/notSet), `date_range` (relative token | absolute
  `[from, to]`) on `SemanticTimeDimension`, server-side allow-list re-validation and
  `limit` clamping in the semantic service.
- **Dashboard filtering is minimal**: `DashboardFilterBar`
  (`frontend/src/components/dashboard/DashboardFilterBar.tsx`) supports exactly **one**
  `SemanticFilter` (member + operator + comma-separated free-text values). It is
  persisted as `dashboard.filters` (the schema allows a list of 20, but the UI uses
  only `[0]`).
- **Per-tile scoping is a heuristic, not configurable**: a tile applies the filter only
  when it is a semantic chart whose first metric's cube matches the filter's cube
  (`DashboardCardTile.tsx`, `cubeOf` comparison).
- **Filter values are free-text only** — no distinct-value dropdowns. Slice A
  explicitly deferred those to Slice C. **No backend distinct-values endpoint exists.**
- A primitive **cross-filter** (click a chart point → set the single dashboard filter)
  and a **`filter` decoration-tile kind** (a free-text slicer) already exist.

**Decisions (approved):**
1. **Everything in one spec** — all four capabilities in one Slice C cycle.
2. **Distinct values via a new grounded endpoint** with server-side search and
   parent-filter constraints (powers value filters and cascading).
3. **Drill-to-detail = grounded detail breakdown** (re-query the semantic layer),
   never raw physical rows (golden rule #3).
4. **Fresh-start on the filter model** — native filters replace the single-filter bar
   and the `filter` decoration tile; no data migration (pre-production).
5. **Architecture: client-orchestrated, server-validated** (Approach 1) — filter
   configs persist on the dashboard; at view time the dashboard resolves each filter to
   Slice-A primitives and passes them per-tile to `useChartData`; the server
   re-validates every member and clamps limits. Rejected: server-side resolved filter
   context (large new backend surface, breaks the per-tile self-render model) and
   spec-rewrite-at-load (muddies saved-spec semantics).

---

## Design

### 1. Data model — `NativeFilter`

A configured filter control on a dashboard. The config (including its **default
selection**) is persisted; the **live in-session selection** is client state seeded from
the default (same pattern `DashboardDetail` already uses via `filterInitFor`). An
editor saving changes updates the defaults.

```
NativeFilter:
  id: str                       # stable id (client-generated uuid)
  kind: "value" | "time" | "numeric"
  label: str | None             # display name; defaults from the member's title
  member: str                   # governed member, fully-qualified (cube.field)
                                #   value   → a dimension
                                #   time    → a time dimension
                                #   numeric → a numeric dimension or measure
  # value-filter fields
  operator: SemanticFilterOperator = "equals"   # equals/notEquals/contains/notContains
  default_values: list[str] = []                # pre-selected values (multi-select)
  # time-filter field
  date_range: DateRange | None                  # reuse Slice A (relative token | [from,to])
  # numeric-filter field
  numeric_range: { min: float | None, max: float | None } | None   # → gte/lte filters
  # scoping
  scope: { mode: "auto" | "tiles", tile_ids: list[uuid] = [] }     # auto = all compatible tiles
  # cascading
  parent_id: str | None         # another value filter whose selection constrains this one's options
  required: bool = False        # if true, the dashboard demands a selection
```

**Resolution to Slice-A primitives** (at view time):
- `value` → one `SemanticFilter { member, operator, values: <selection> }`.
- `time` → a `date_range` injected onto the matching time dimension.
- `numeric` → up to two `SemanticFilter`s (`gte` min, `lte` max).

### 2. Backend — `backend/app/schemas/dashboard.py`

- **Replace** `filters: list[SemanticFilter]` with `native_filters: list[NativeFilter]`
  (max 20) on `DashboardRead` and `DashboardUpdate`.
- **Remove** `"filter"` from `TileKind` (the slicer decoration tile is gone).
- New Pydantic models: `NativeFilter`, `FilterScope`, `NumericRange`. Validate at the
  boundary:
  - known `kind`; `member` shape; `scope.mode` enum.
  - `parent_id` references an existing **value** filter in the same list and introduces
    **no cycle** (walk the parent chain).
  - `numeric_range.min ≤ max` when both present.
  - `date_range` reuses Slice A's validator.
- Members are **re-validated against the governed allow-list** by the semantic query
  path when a tile runs — persisting a filter never widens data access (golden rule #3).

### 3. Backend — distinct-values endpoint (`POST /semantic/values`)

```
request:  { member: str, search?: str, constraints?: SemanticFilter[], limit?: int }
response: { values: string[] }
```

- Builds a **grounded** Cube query: `dimensions=[member]`, `order={member: "asc"}`,
  `limit` clamped to a new `settings.max_filter_values` (golden rule #1 — no hardcoded
  cap). `search` becomes a `contains` `SemanticFilter` on `member`; `constraints` are
  the parent filters (cascading). No measure required — querying the lone dimension
  returns its distinct values.
- **Read-only, tenant-scoped** from `TenantContext`. `member`, every
  `constraints[].member`, and the search target are re-validated against the governed
  allow-list before reaching Cube; an ungoverned member → **422, never calls Cube**.
- Frequency ordering (needs a governed count measure) is **out of scope**; alphabetical.

### 4. Contract / type mirror

- Mirror `NativeFilter` / `FilterScope` / `NumericRange` and the `/semantic/values`
  request+response into `frontend/src/types/api.ts` (snake_case, field-for-field).
- Remove `"filter"` from the frontend `TileKind`.

### 5. Filter panel — collapsible left drawer

A **collapsible left-hand drawer** (Superset-style), a new component
(`DashboardFilterDrawer`) replacing `DashboardFilterBar`. Collapses via a toggle and on
narrow viewports.

**View mode** — one control per native filter, listed vertically:
- **value** → searchable multi-select dropdown; options from `/semantic/values`
  (narrowed by the parent's selection when cascading).
- **time** → the Slice-A time-range control (presets + Custom + No filter).
- **numeric** → a min/max range input.
- A **"Clear all"** resets every filter to its configured default; an empty `required`
  filter surfaces an inline prompt.

**Edit mode** — an **"Add filter"** button opens a **filter-editor dialog**:
- Pick **kind** → **target member** (from the tenant's governed semantic models via
  `useSemanticModels`) → **label**.
- Per kind: default selection / operator (value), default range (numeric), default date
  range (time).
- **Scope**: "All compatible tiles" (auto) or pick specific tiles by title.
- **Cascading**: optional **parent** (value filters only; the editor blocks cycles).
- **Required** toggle. Existing filters can be edited, reordered, and removed.

Filter configs persist on the dashboard for editors (`useUpdateDashboard`); a read-only
viewer's selections stay local (mirrors today's `handleFilterChange` behaviour).

### 6. Per-tile application

For each tile the dashboard computes the applicable filters. A filter applies iff:

- **auto scope** AND the tile's cube contains the filter's member, **OR**
- **tile scope** AND `tile.id ∈ scope.tile_ids` AND the tile's cube contains the member.

The **cube-compatibility check always holds**, so a filter can never break an unrelated
tile (keeps today's safety guarantee). Applicable `value`/`numeric` filters resolve to
`SemanticFilter[]` and merge through `buildSemanticRequest` (spec filters first, then
view filters — unchanged). `time` filters inject a `date_range` onto the tile spec's
matching time dimension at view time — a small `useChartData` extension accepting a
view-time `date_range` override keyed by time-dimension member.

The **click-to-cross-filter overlay still layers on top**, but — because the persisted
single-filter model is removed — it is now a **transient session value overlay** (an
ad-hoc `SemanticFilter` merged into the applicable filters for the current view), no
longer written back to the dashboard. Promoting a cross-filter to a persisted
`NativeFilter` is out of scope.

### 7. Cascading

A child value filter's `/semantic/values` request carries its parent's current selection
as `constraints`. When the parent changes, the child re-fetches options (TanStack Query
keyed on parent selection) and drops any selected values no longer present. Cycles are
prevented at config time (section 2).

### 8. Drill-by

- **Trigger**: the Slice-A `ChartActionsMenu` gains a **"Drill by →"** action; a clicked
  data point provides `{dimension, value}` (a small `ChartRenderer` extension surfacing
  the clicked point, beyond today's category string).
- **Action**: a **drill modal** where the user picks another governed dimension of the
  same cube (excluding ones already encoded). It runs a **grounded** query — same
  metric(s), grouped by the chosen dimension, filtered to the clicked point
  (`member equals value`) plus any active dashboard filters scoped to that tile — and
  renders via `ChartRenderer` from a derived `ChartSpec`. Reuses `/semantic/query`; no
  backend change.

### 9. Drill-to-detail

- **Trigger**: `ChartActionsMenu` **"Drill to detail"**.
- **Action**: a **detail modal** showing a `TableRenderer` of the metric(s) broken down
  by the cube's **remaining governed dimensions**, filtered to the clicked point + any
  active scoped filters. A grounded re-query via `/semantic/query` — **never raw
  physical rows** (golden rule #3). Read-only.

### 10. Tenancy & golden-rule compliance

- **#1 (no hardcoded config)**: distinct-values cap from `settings.max_filter_values`;
  no hardcoded members, limits, or paths; relative `date_range` tokens stay a closed set.
- **#2 (tenancy)**: tenant resolved server-side from `TenantContext`; the client never
  supplies a tenant id; filter configs persist under the tenant's dashboard.
- **#3 (grounded, read-only, validated)**: every member (filter target, search,
  constraints, drill dimension, clicked-point member) is re-validated against the
  governed Cube allow-list before any query; all reads are read-only; drill-to-detail is
  a grounded semantic breakdown, not raw tables; no SQL surface anywhere.

---

## Testing (definition of done)

**Backend (pytest + ruff + mypy):**
- `NativeFilter` validation: accepts each kind; rejects unknown kind, bad `scope.mode`,
  a `parent_id` cycle, a non-value parent, `numeric_range` with `min > max`, malformed
  `date_range`.
- `/semantic/values`: builds the grounded query (search → `contains`, constraints
  forwarded); rejects an ungoverned `member`/constraint with **422 without calling
  Cube**; `limit` clamped to `settings.max_filter_values`; tenant-scoped.
- Dashboard round-trips `native_filters`; the `"filter"` tile kind is **removed**
  (creating one is rejected).

**Frontend (Vitest + RTL + tsc + eslint):**
- Filter resolution: `value` → `SemanticFilter`, `time` → `date_range`, `numeric` →
  `gte`/`lte`.
- Scoping: auto vs tile-scope; the cube-compatibility safety check prevents a filter
  from applying to an incompatible tile.
- Cascading: the child request carries the parent's selection as constraints; stale
  child selections are pruned when the parent changes.
- Filter-editor dialog: add / edit / remove; cycle prevention.
- Drawer: collapse/expand, "Clear all", `required` empty-state prompt.
- Drill-by: the derived spec groups by the chosen dimension and filters to the clicked
  point; grounded request shape.
- Drill-to-detail: the detail-table query requests the remaining dimensions + the
  point filter.
- `useChartData`: a view-time `date_range` override is injected onto / overrides the
  matching time dimension; existing behaviour unchanged for tiles without an override.

**Docs:** update the dashboards docs page — native filters (value/time/numeric),
per-tile scoping, cascading, drill-by/drill-to-detail; note the removal of the
single-filter bar and the `filter` decoration tile.

---

## Out of scope (this slice)

- **Frequency-ordered** distinct values (needs a governed count measure) — alphabetical.
- **URL-shareable** live filter selection — we persist *defaults*; the live selection is
  session state.
- Native filters on **dataset** (non-semantic) tiles — semantic tiles only, as today.
- Numeric **slider** with served min/max bounds — plain min/max inputs this slice.
- Adhoc **SQL** filters / raw datasets / SQL Lab → **never** (golden rule #3).
- Dashboard layout / tabs / resize → **slice B**. New viz types → **slice D**.
