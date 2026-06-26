# Superset-parity for charts & dashboards — Slice A: Chart-builder (Explore) parity

**Date:** 2026-06-26
**Status:** Design approved; ready for implementation plan
**Branch:** `feat/phase-2-widen` (current); slice will get its own feature branch

---

## Program context (why this spec exists)

We want NovaSight's charts & dashboard modules to reach feature parity with Apache
Superset's, **adopting Superset's patterns re-implemented in NovaSight's existing
stack** (React + TS + Vite, shadcn/ui + Tailwind, ECharts, dnd-kit, Zustand,
TanStack Query) — *not* porting Superset's Ant Design / Redux / raw-SQL-dataset
components. This preserves the five golden rules, most importantly rule #3
(AI/queries are grounded on the **governed semantic layer** — Cube — never raw
physical tables or arbitrary SQL).

The work is decomposed into four ordered slices, each with its own
spec → plan → build cycle:

| Slice | Theme | Status |
|-------|-------|--------|
| **A** | **Chart-builder (Explore) parity** — query shaping + chart actions | **this spec** |
| A2 | Per-type formatting parity — Superset "Customize" panel | spec done |
| C | Native filters — typed filter panel (value/time/numeric), per-tile scoping, cascading, drill-by/drill-to-detail | later |
| B | Dashboard layout — free-resize tiles, nested rows/columns, tabs, header, fullscreen, auto-refresh | later |
| D | More viz types & options — pivot table, big-number-with-trend, heatmap, box plot, conditional table formatting, color schemes, annotations | later |

Sequence rationale: A introduces the **query-filter primitives** (time-range, value,
numeric) at the query layer; **A2** makes formatting type-aware (both A and A2 edit the
builder configure panel, so they run back-to-back to minimise churn); C reuses A's
primitives for dashboard-level native filters, so it becomes mostly UI + scoping; B is
a structural layout refactor independent of filters; D is purely additive breadth.
A2 is the program's single breaking-change checkpoint (`ChartSpec` v1 → v2).

Deliberately **excluded from the whole program** (would violate golden rule #3):
adhoc *SQL* metrics, raw-dataset/SQL-Lab access, any path that reaches ungoverned
physical tables.

---

## Slice A — goals

Bring the chart builder to Superset-Explore parity on **query shaping** and **chart
actions**, within the semantic-layer-only model:

- **Time-range filtering** — the single biggest gap today (only granularity exists).
- **Per-chart filters** — governed members + the existing operator set.
- **Row limit** and **server-side sort** ("Sort by").
- **Chart actions** — View as table · View query · Download CSV · Download PNG.

Everything persists on the `ChartSpec`, so **saved charts and dashboard tiles
reproduce it automatically**. No dashboard or AI-path code changes in this slice;
both benefit for free because they render the same spec through the same renderer
and the same `useChartData` hook.

---

## Current state (what already exists)

- **Backend `SemanticQueryRequest`** (`backend/app/schemas/semantic.py`) **already**
  accepts `filters` (10 operators: equals/notEquals/contains/notContains/gt/gte/lt/
  lte/set/notSet), `order` (`{member: "asc"|"desc"}`), and a `limit` clamped to
  `settings.max_query_rows` in the service.
- **`SemanticTimeDimension`** has `dimension` + optional `granularity` — but **no
  date range**. Cube's `dateRange` is therefore never sent.
- **`ChartQuery`** (`backend/app/schemas/chart.py` + mirror in
  `frontend/src/types/api.ts`) persists only `metric_refs`, `dimensions`,
  `time_dimensions`. It does **not** carry `filters`/`order`/`limit`, so a *saved*
  chart cannot remember them even though a live query could apply them.
- **`useChartData`** (`frontend/src/lib/useChartData.ts`) hardcodes
  `DEFAULT_LIMIT = 200` and forwards only measures/dimensions/time_dimensions
  (+ caller-supplied view-time filters). It ignores any spec-level filters/order/limit.
- **Builder** (`frontend/src/pages/Builder.tsx` + `SemanticQueryBuilder.tsx`) exposes
  three shelves (X / Breakdown / Metrics), granularity, chart type, and display
  formatting — but no filters, no time range, no row limit, no server sort, and no
  view/export actions.
- **`SemanticLayerClient._build_body`** (`backend/app/ai/semantic/client.py`) already
  forwards `timeDimensions`, `order`, `limit`, `filters` to Cube — so the time
  dimension's new `date_range` rides along once it's on the dict.

**Decision (approach 1, approved):** persist the new query-shaping controls on
`ChartSpec.query`. Rejected alternatives: view-time-only (saved charts forget their
filters; dashboards can't reproduce them) and a separate saved-query entity
(`ChartQuery` already *is* the structured query — a second entity is needless
plumbing + a migration).

---

## Design

### 1. Backend (small, additive)

**`schemas/semantic.py`**
- Add `date_range` to `SemanticTimeDimension`, accepting **either**:
  - a **relative token** from a closed set, each mapping 1:1 to a Cube relative
    date-range string via a single lookup table:
    | token | Cube `dateRange` |
    |-------|------------------|
    | `last_7_days` | `"last 7 days"` |
    | `last_30_days` | `"last 30 days"` |
    | `last_90_days` | `"last 90 days"` |
    | `this_month` | `"this month"` |
    | `last_month` | `"last month"` |
    | `this_quarter` | `"this quarter"` |
    | `last_quarter` | `"last quarter"` |
    | `this_year` | `"this year"` |
    | `last_year` | `"last year"` |
  - an **absolute `[from, to]`** pair of ISO dates (`YYYY-MM-DD`), passed through to
    Cube as `[from, to]`.
- Validate at the boundary (Pydantic): reject unknown tokens, malformed dates, or a
  pair that isn't exactly two valid ordered dates. `None`/absent = no time filter.
- "Year to date" / other custom windows are expressed via the absolute `[from, to]`
  pair (the builder's Custom range), so the relative set stays a clean 1:1 Cube map
  with no computed-date logic in the schema.

**`schemas/chart.py`**
- `ChartQuery` gains (all optional, default-empty, backward compatible):
  - `filters: list[SemanticFilter]`
  - `order: dict[SemanticRef, OrderDir]`
  - `limit: int | None` (`ge=1`)
  - (`date_range` rides on the existing `time_dimensions` entries — no new field here.)
  - Imports `SemanticFilter`, `SemanticRef`, `OrderDir` from `schemas/semantic.py`.

**Semantic service** (`backend/app/services/semantic.py` / `app/api/v1/semantic.py`)
- Confirm the existing allow-list re-validation covers `filters[].member` and every
  `order` key for the spec-sourced path (it already does for the request path). Add a
  test asserting an ungoverned filter member → 422/400, never reaching Cube.
- `limit` continues to be clamped to `settings.max_query_rows`. Nothing hardcoded.

### 2. Contract / type mirror

- Mirror the three new `ChartQuery` fields and `date_range` into
  `frontend/src/types/api.ts` (snake_case, field-for-field).
- Update `docs/CHART_SPEC.md` and the round-trip proof (`tests/test_chart_spec.py`).
- `version` stays `"1"` — additive, backward-compatible (legacy specs default empty).

### 3. Builder UI

A new **Query** section in the configure panel (above Formatting), in
`Builder.tsx` + `SemanticQueryBuilder.tsx`:

- **Filters shelf** — a 4th dnd-kit shelf. Dropping a dimension/measure opens a small
  popover: choose **operator** (the 10 governed ops) + **value(s)** (typed text in
  this slice; presence ops `set`/`notSet` take no value). Placed filters render as
  removable chips like the other shelves. Emits `query.filters`.
- **Time range** — appears next to the existing Granularity select when the X
  dimension is `time`. Presets (the closed relative set) + **Custom** (two date
  inputs) + **No filter** (omit). Emits `date_range` on the time dimension.
- **Row limit** — numeric input (default 50; clamped server-side). Emits `query.limit`.
- **Sort by** — member select + asc/desc → `query.order`. This is the **server**
  order (correct for top-N with a row limit). The existing client-side `options.sort`
  is retained as quick display reordering; the two are labelled distinctly
  ("Sort by (query)" vs "Reorder (display)") to avoid confusion.
- `loadSpec` restores filters / date_range / limit / order into the controls when a
  saved chart is opened for editing.

### 4. Chart actions

New `frontend/src/components/chart/ChartActionsMenu.tsx`, reused by the builder
preview and by dashboard chart tiles. A "⋯" menu with:

- **View as table** — render the current `QueryResponse` via the existing
  `TableRenderer` (no re-query; pure client toggle).
- **View query** — a dialog showing the structured **semantic** query (read-only
  JSON). Never raw SQL (golden rule #3).
- **Download CSV** — client-side CSV from `QueryResponse` rows via a new
  `frontend/src/lib/csv.ts` util.
- **Download PNG** — via ECharts `getDataURL()`. `ChartRenderer` gains a **forwarded
  ref** exposing an imperative `toPng(): string | null` handle (returns `null` for
  non-ECharts renders); the PNG action is hidden for `table`/`number` tiles.

### 5. `useChartData`

- Forward `spec.query.filters`, `spec.query.order`, `spec.query.limit` into the
  `SemanticQueryRequest`.
- **Merge** spec-level filters with caller view-time filters (dashboard filter layers
  on top of the chart's own filters).
- Replace the hardcoded `DEFAULT_LIMIT` with `spec.query.limit ?? 200` (200 keeps the
  current behaviour for legacy specs that carry no limit; the builder defaults new
  charts to 50).

### 6. Tenancy & golden-rule compliance

- All filter members and order keys are re-validated against the tenant's governed
  Cube allow-list server-side (rule #3, `nl-to-sql-grounding` / `tenancy-isolation`).
- "View query" exposes only the **semantic** query intent — no SQL surface.
- `limit` clamped to the platform max; relative `date_range` tokens are a closed set;
  nothing environment- or tenant-specific is hardcoded (rule #1).
- Tenant scope is still resolved server-side from `TenantContext`; the client never
  supplies a tenant id (rule #2).

---

## Testing (definition of done)

**Backend (pytest + ruff + mypy):**
- `date_range` validation: accepts each relative token and a valid ISO pair; rejects
  unknown tokens, malformed/single/unordered dates.
- Cube body includes the mapped `dateRange` for both relative and absolute inputs.
- `ChartQuery` round-trips `filters`/`order`/`limit` (extend `test_chart_spec.py`).
- Allow-list re-validation rejects an ungoverned filter member / order key without
  calling Cube.
- `limit` clamped to `settings.max_query_rows`.

**Frontend (Vitest + RTL + tsc + eslint):**
- Builder emits a spec with correct `filters` / `date_range` / `limit` / `order`.
- `loadSpec` restores all new controls from a saved spec.
- `useChartData` forwards limit/order and merges spec + view-time filters.
- `csv.ts` produces correct CSV (escaping, headers).
- `ChartActionsMenu` renders the right actions per chart type (no PNG for table/number).
- `buildEChartsOption` behaviour unchanged for existing specs (regression).

**Docs:** `docs/CHART_SPEC.md` updated to describe the new `ChartQuery` fields and
`date_range`.

---

## Out of scope (this slice)

- Real distinct-value dropdowns for filter values → **slice C** (native filters).
- Adhoc **SQL** metrics, raw datasets, SQL Lab → **never** (golden rule #3).
- Dashboard layout / tabs / resize → **slice B**.
- Drill-down / drill-by → **slice C**.
- New viz types → **slice D**.
