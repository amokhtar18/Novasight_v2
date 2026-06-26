# Slice D Final Review — Fix Report

Generated: 2026-06-27

---

## I1 — Sankey x/y node-name collision (correctness)

### Production change

**File:** `frontend/src/components/chart/ChartRenderer.tsx`, `buildSankeyOption`

**Before:**
```ts
const src = String(r[xIdx]);
let tgt = String(r[yIdx]);
if (src === tgt) tgt += "​"; // zero-width suffix to break a self-cycle
```

**After:**
```ts
const src = String(r[xIdx]);
const tgt = String(r[yIdx]) + "​"; // always suffix targets → x/y namespaces never collide
```

The change makes x-side (source) and y-side (target) node namespaces unconditionally
disjoint. The self-cycle case is now a natural subset (a suffixed target that still
differs from its un-suffixed source). The label formatter and `selectionPairsFromClick`
already stripped the suffix via `replace(/​/g, "")` — no changes needed there.

---

### I1 test updates

**File:** `frontend/src/test/chartRenderer.test.ts`

1. **Updated:** `describe("buildEChartsOption — sankey") > "builds nodes from both dimensions and weighted links"`
   - `nodeNames` now asserts `toContain("Widget​")` (suffixed target)
   - `links` now asserts `{ source: "West", target: "Widget​", value: 10 }`
   - Source assertions (`"West"`) unchanged.

2. **Confirmed passing (unchanged):** Self-cycle test (`["West","West",5]` → `target: "West​"`)
   passes — the unconditional suffix produces the same result as the old conditional suffix for
   the self-cycle case.

3. **Added:** Disjoint namespace regression test:
   - Data: `rows: [["North","South",10],["South","North",5]]`
   - Asserts `nodeNames` contains all four distinct nodes:
     `"North"`, `"South"` (x-sources, un-suffixed) and `"North​"`, `"South​"` (y-targets, suffixed)
   - Also asserts `nodeNames` has exactly 4 entries — no merging across dimensions.

---

## I2 — Cross-filter replacement semantics (doc)

**File:** `docs/DASHBOARDS.md`, section "Cross-filtering from chart clicks"

Added one sentence at the end of the section:

> Only the most recently clicked chart's filter(s) form the cross-filter overlay —
> clicking a new point (or cell) replaces any prior overlay rather than accumulating
> across charts.

No restructuring; the sentence was appended inline after the existing heatmap/sankey paragraph.

---

## I3 — Integration test for handleCrossFilter wiring

**File:** `frontend/src/test/dashboardDetailFilters.test.tsx`

### Approach

The existing file rendered `DashboardDetail` end-to-end but previously mocked neither
`ChartRenderer` nor `dnd-kit`. For the cross-filter test to work, three additional
mock layers were added:

1. **`@/components/chart/ChartRenderer`** — mirrors the pattern in
   `dashboardCardTile.test.tsx`: renders a "point" `<button>` when `onSelectPoints`
   is wired, clicking which fires `onSelectPoints([{ member: "regional_sales.region", value: "west" }])`.

2. **`@dnd-kit/core`, `@dnd-kit/sortable`, `@dnd-kit/utilities`** — JSDOM stubs
   required so `DashboardGrid` (which uses `DndContext`/`SortableContext`/`useSortable`)
   renders without error.

3. **`useSetDashboardLayout`** added to the `@/api/hooks` mock (consumed by `DashboardGrid`).

4. **`useChartData`** changed from a static factory to `vi.fn()` so the I3 test can
   override its return value to `row_count: 1` — `DashboardCardTile` only renders
   `ChartRenderer` (and therefore the "point" button) when `data.row_count > 0`.

### The test

`describe("DashboardDetail cross-filter wiring") > "maps SelectionPair[] from a tile click to SemanticFilter[] and propagates it to tiles"`:

1. Overrides `useChartData` to return a one-row QueryResponse so `ChartRenderer` renders.
2. Renders `DashboardDetail` with `boardWithFilter` (one chart tile, one native filter).
3. Clicks the "point" button on the mocked `ChartRenderer`.
4. Asserts that the last `useChartData` call received
   `[{ member: "regional_sales.region", operator: "equals", values: ["west"] }]`
   as its second argument (`appliedFilters`), proving the full wiring:
   `SelectionPair[]` → `handleCrossFilter` → `SemanticFilter[]` → `crossFilter` state
   → `DashboardGrid` → `DashboardCardTile` → merged into `appliedFilters` → `useChartData`.

### Note on wiring detail

`DashboardCardTile` merges `crossFilter` into its local `appliedFilters` array (alongside
resolved native filters) and passes the combined result as the second argument to
`useChartData(spec, appliedFilters, dateRangeOverrides)` — there is no separate
"crossFilter argument". The test asserts `lastCall[1]` (the second argument) equals the
derived `SemanticFilter[]`. This is the correct assertion path.

### Limitations

The test relies on the `ChartRenderer` mock exposing a synthetic "point" button, not a
real ECharts click event. This is the accepted project convention for cross-filter testing
(identical pattern to `dashboardCardTile.test.tsx`).

---

## Full-gate output

```
tsc:  0 errors
lint: 0 errors, 44 warnings (all pre-existing @typescript-eslint/no-explicit-any in test files)
test: 41 test files, 235 tests — all passed
```
