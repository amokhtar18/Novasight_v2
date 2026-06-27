# Dashboard View Redesign (Command Center) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the dashboard view into a top filter-bar command center — filters as a horizontal bar, a full-width gridstack canvas, and polished tile chrome — reusing all filter/grid/chart logic.

**Architecture:** A new horizontal `DashboardFilterBar` reuses the existing per-filter controls + cascading + selection callbacks (replacing the left `DashboardFilterDrawer`); `DashboardDetail` stacks header → filter bar → full-width `DashboardGrid`; `DashboardCardTile`'s wrapper gets glass/elevation/hover polish. The gridstack engine, dialogs, and grounded query/filter logic are untouched.

**Tech Stack:** React 19, TypeScript, Vite 8, Tailwind v4, gridstack (mocked in jsdom), Vitest + Testing Library.

## Global Constraints

- **Off-limits (reuse, do NOT modify):** `DashboardGrid` gridstack mechanics; `dialog.tsx` (user WIP); the filter-control components (`ValueFilterControl`/`TimeFilterControl`/`NumericFilterControl`); `resolveTileFilters`/`useChartData`/cross-filter/drill logic; `NativeFilterEditor`; `AddObjectDialog`.
- **Reuse the filter logic:** the bar renders the SAME controls with the SAME props the drawer used: `ValueFilterControl({ filter, values, onChange, constraints, enabled })`, `TimeFilterControl({ value, onChange, label })`, `NumericFilterControl({ min, max, onChange, label })`. Cascading via `parentConstraints` (moved from the drawer into the bar). `Props` shape identical to `DashboardFilterDrawer`.
- **Preserve filter handles:** each filter's `Label` text (`f.label ?? f.member`), the control `aria-label`s, the `Clear all` button, the `Add filter` button (edit mode), and `Edit {label}` buttons — existing dashboard suites query these.
- **Tile chrome is styling-only:** change only the wrapper/header classes of `DashboardCardTile` + add a chart loading skeleton; do NOT touch `TileBody`/`ChartTileBody`/drill/cross-filter/`useChartData`.
- **Hardened primitives + tokens** (`--elevation-*`); no new tokens; no new deps.
- **Not jsdom-testable:** gridstack drag/resize, full-width visual layout, hover-lift → `pnpm build` + a manual browser smoke (user step).
- Unrelated user WIP exists (dialog.tsx, backend, configs). Each task `git add`s ONLY its files; never `git add -A`/`.`. `docs/FRONTEND.md` (Task 4) is controller-handled via stash. `DashboardDetail.tsx` is NOT in WIP (no commit prerequisite).
- Run from `d:\Novasight_v2\frontend`. `@/` alias → `frontend/src/`. Commit after each task.

## File structure

- Create `frontend/src/components/dashboard/DashboardFilterBar.tsx` (Task 1).
- Create `frontend/src/test/dashboardFilterBar.test.tsx` (Task 1).
- Modify `frontend/src/pages/DashboardDetail.tsx` (Task 2) — swap drawer → bar + full-width canvas + header refine.
- Delete `frontend/src/components/dashboard/DashboardFilterDrawer.tsx` (Task 2, once unused).
- Modify `frontend/src/components/dashboard/DashboardCardTile.tsx` (Task 3) — chrome only.
- Modify `docs/FRONTEND.md` (Task 4, controller).

---

### Task 1: `DashboardFilterBar` (horizontal, reuses the controls)

**Files:**
- Create: `frontend/src/components/dashboard/DashboardFilterBar.tsx`
- Test: `frontend/src/test/dashboardFilterBar.test.tsx`

**Interfaces:**
- Consumes: the three filter controls; `defaultSelection`, `FilterSelection`/`FilterSelections` from `@/lib/dashboardFilters`; `NativeFilter`/`SemanticFilter` types.
- Produces: `export function DashboardFilterBar(props)` where `props` is identical to the drawer's `Props` (`filters`, `selections`, `onSelectionChange`, `onClearAll`, `editing`, `onAddFilter?`, `onEditFilter?`).

- [ ] **Step 1: Write the failing test**

Create `frontend/src/test/dashboardFilterBar.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { DashboardFilterBar } from "@/components/dashboard/DashboardFilterBar";
import type { NativeFilter } from "@/types/api";

vi.mock("@/api/hooks", async () => {
  const actual = await vi.importActual<typeof import("@/api/hooks")>("@/api/hooks");
  return { ...actual, useSemanticValues: () => ({ data: { values: ["west", "east"] }, isLoading: false }) };
});

const filters: NativeFilter[] = [
  { id: "f1", kind: "value", member: "regional_sales.region", operator: "equals", label: "Region" },
];

function renderBar(props: Partial<React.ComponentProps<typeof DashboardFilterBar>> = {}) {
  const qc = new QueryClient();
  const onSelectionChange = vi.fn();
  const onClearAll = vi.fn();
  const onAddFilter = vi.fn();
  render(
    <QueryClientProvider client={qc}>
      <DashboardFilterBar
        filters={filters}
        selections={{}}
        onSelectionChange={onSelectionChange}
        onClearAll={onClearAll}
        editing={false}
        onAddFilter={onAddFilter}
        onEditFilter={vi.fn()}
        {...props}
      />
    </QueryClientProvider>
  );
  return { onSelectionChange, onClearAll, onAddFilter };
}

describe("DashboardFilterBar", () => {
  it("renders each filter's label in the bar", () => {
    renderBar();
    expect(screen.getByText("Region")).toBeInTheDocument();
  });

  it("calls onClearAll from the Clear all button", () => {
    const { onClearAll } = renderBar();
    fireEvent.click(screen.getByRole("button", { name: /clear all/i }));
    expect(onClearAll).toHaveBeenCalled();
  });

  it("shows Add filter only in edit mode", () => {
    renderBar({ editing: false });
    expect(screen.queryByRole("button", { name: /add filter/i })).not.toBeInTheDocument();
    renderBar({ editing: true });
    expect(screen.getByRole("button", { name: /add filter/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pnpm exec vitest run src/test/dashboardFilterBar.test.tsx`
Expected: FAIL — cannot resolve `@/components/dashboard/DashboardFilterBar`.

- [ ] **Step 3: Create the bar**

Create `frontend/src/components/dashboard/DashboardFilterBar.tsx`:

```tsx
/**
 * DashboardFilterBar — horizontal top bar of native filters (command-center layout).
 * One control per filter (value/time/numeric); reuses the same controls + cascading
 * the left drawer used, laid out inline. In edit mode it exposes Add/Edit.
 */
import { Filter, Pencil, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { ValueFilterControl } from "./filterControls/ValueFilterControl";
import { TimeFilterControl } from "./filterControls/TimeFilterControl";
import { NumericFilterControl } from "./filterControls/NumericFilterControl";
import { defaultSelection } from "@/lib/dashboardFilters";
import type { FilterSelection, FilterSelections } from "@/lib/dashboardFilters";
import type { NativeFilter, SemanticFilter } from "@/types/api";

interface Props {
  filters: NativeFilter[];
  selections: FilterSelections;
  onSelectionChange: (id: string, sel: FilterSelection) => void;
  onClearAll: () => void;
  editing: boolean;
  onAddFilter?: () => void;
  onEditFilter?: (id: string) => void;
}

/** Parent selection of a value filter expressed as a constraint for cascading. */
function parentConstraints(filter: NativeFilter, all: NativeFilter[], selections: FilterSelections): SemanticFilter[] {
  if (!filter.parent_id) return [];
  const parent = all.find((f) => f.id === filter.parent_id);
  if (!parent) return [];
  const sel = selections[parent.id] ?? defaultSelection(parent);
  if (sel.kind === "value" && sel.values.length > 0) {
    return [{ member: parent.member, operator: parent.operator ?? "equals", values: sel.values }];
  }
  return [];
}

export function DashboardFilterBar({
  filters, selections, onSelectionChange, onClearAll, editing, onAddFilter, onEditFilter,
}: Props) {
  if (filters.length === 0 && !editing) return null;

  return (
    <div className="mb-4 flex flex-wrap items-end gap-3 rounded-xl border bg-card/40 p-3 shadow-[var(--elevation-1)]">
      <span className="flex h-9 items-center gap-1.5 text-sm font-medium">
        <Filter className="h-4 w-4" aria-hidden /> Filters
      </span>

      {filters.map((f) => {
        const sel = selections[f.id] ?? defaultSelection(f);
        return (
          <div key={f.id} className="flex min-w-[10rem] flex-col gap-1">
            <div className="flex items-center justify-between">
              <Label className="text-xs text-muted-foreground">
                {f.label ?? f.member}{f.required ? " *" : ""}
              </Label>
              {editing && onEditFilter && (
                <button type="button" aria-label={`Edit ${f.label ?? f.member}`} onClick={() => onEditFilter(f.id)} className="text-muted-foreground hover:text-foreground">
                  <Pencil className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
            {f.kind === "value" && sel.kind === "value" && (
              <ValueFilterControl
                filter={f}
                values={sel.values}
                onChange={(values) => onSelectionChange(f.id, { kind: "value", values })}
                constraints={parentConstraints(f, filters, selections)}
                enabled={!editing}
              />
            )}
            {f.kind === "time" && sel.kind === "time" && (
              <TimeFilterControl
                value={sel.date_range}
                onChange={(date_range) => onSelectionChange(f.id, { kind: "time", date_range })}
                label={f.label ?? f.member}
              />
            )}
            {f.kind === "numeric" && sel.kind === "numeric" && (
              <NumericFilterControl
                min={sel.min}
                max={sel.max}
                onChange={({ min, max }) => onSelectionChange(f.id, { kind: "numeric", min, max })}
                label={f.label ?? f.member}
              />
            )}
            {f.required && sel.kind === "value" && sel.values.length === 0 && (
              <p className="text-xs text-amber-600">A selection is required.</p>
            )}
          </div>
        );
      })}

      <div className="ml-auto flex items-center gap-2">
        {filters.length > 0 && (
          <Button variant="ghost" size="sm" onClick={onClearAll}>Clear all</Button>
        )}
        {editing && onAddFilter && (
          <Button variant="outline" size="sm" onClick={onAddFilter}>
            <Plus className="h-4 w-4" aria-hidden /> Add filter
          </Button>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pnpm exec vitest run src/test/dashboardFilterBar.test.tsx`
Expected: PASS (3 tests).

- [ ] **Step 5: Type check + lint**

Run: `pnpm exec tsc --noEmit && pnpm lint`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/dashboard/DashboardFilterBar.tsx frontend/src/test/dashboardFilterBar.test.tsx
git commit -m "feat(dashboard): horizontal DashboardFilterBar (reuses filter controls + cascading)"
```

---

### Task 2: Wire the bar into `DashboardDetail` (top bar + full-width canvas)

**Files:**
- Modify: `frontend/src/pages/DashboardDetail.tsx`
- Delete: `frontend/src/components/dashboard/DashboardFilterDrawer.tsx`

**Interfaces:**
- Consumes: `DashboardFilterBar`.
- Produces: the command-center page layout.

- [ ] **Step 1: Swap the layout**

In `frontend/src/pages/DashboardDetail.tsx`:
- Replace the import `import { DashboardFilterDrawer } from "@/components/dashboard/DashboardFilterDrawer";` with `import { DashboardFilterBar } from "@/components/dashboard/DashboardFilterBar";`.
- Replace the `flex gap-4` block (the drawer + canvas, current lines ~220–243) with a vertical stack — the bar on top, the full-width canvas below:

```tsx
        <div className="min-w-0">
          {(filters.length > 0 || editing) && (
            <DashboardFilterBar
              filters={filters}
              selections={selections}
              onSelectionChange={onSelectionChange}
              onClearAll={onClearAll}
              editing={editing}
              onAddFilter={() => setEditorFor({ open: true, id: null })}
              onEditFilter={(id) => setEditorFor({ open: true, id })}
            />
          )}
          <DashboardGrid
            tiles={board.tiles}
            dashboardId={board.id}
            editing={editing}
            filters={filters}
            selections={selections}
            crossFilter={editing ? [] : crossFilter}
            onCrossFilter={editing ? undefined : handleCrossFilter}
          />
        </div>
```

All filter state/handlers (`selections`, `crossFilter`, `saveFilter`, `removeFilter`, `handleCrossFilter`, seeding, `onSelectionChange`, `onClearAll`) and the `AddObjectDialog`/`NativeFilterEditor` blocks are UNCHANGED.

- [ ] **Step 2: Delete the now-unused drawer**

Run: `grep -rn "DashboardFilterDrawer" src` — confirm the only references are its own file + (now-removed) the import you just replaced. Then delete `frontend/src/components/dashboard/DashboardFilterDrawer.tsx`.

> If `grep` shows any OTHER importer, STOP — do not delete; report it.

- [ ] **Step 3: Run the dashboard suites (the gate)**

Run: `pnpm exec vitest run src/test/dashboardDetailFilters.test.tsx src/test/cascadingFilters.test.tsx src/test/dashboardCardTile.test.tsx src/test/dashboardGrid.test.tsx src/test/nativeFilterEditor.test.tsx`
Expected: PASS — these query the filter by label ("Region"), the "Add filter" button, control `aria-label`s, and cross-filter wiring, all preserved by the bar. (If any test asserts a drawer-only handle like "Collapse filters", rewrite that assertion for the bar — not weaken it. `dashboardDetailFilters.test.tsx` has none.)

- [ ] **Step 4: Type check + lint**

Run: `pnpm exec tsc --noEmit && pnpm lint`
Expected: PASS (no dangling `DashboardFilterDrawer` import).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/DashboardDetail.tsx frontend/src/components/dashboard/DashboardFilterDrawer.tsx
git commit -m "feat(dashboard): top filter-bar + full-width canvas (replaces left drawer)"
```

---

### Task 3: Polish `DashboardCardTile` chrome

**Files:**
- Modify: `frontend/src/components/dashboard/DashboardCardTile.tsx`
- Test: `frontend/src/test/dashboardCardTile.test.tsx` (extend with a chrome assertion)

**Interfaces:** none new — styling only (+ one optional chrome test).

- [ ] **Step 1: Add a failing chrome assertion**

In `frontend/src/test/dashboardCardTile.test.tsx`, add a test asserting the tile wrapper uses the elevation token (find the existing render helper in that file and reuse it; the wrapper is the outermost tile div). Example (adapt to the file's existing harness/queries):

```tsx
  it("uses the elevation-token chrome (not a flat shadow-sm)", () => {
    // render a tile via the file's existing helper, then:
    const card = screen.getByText(/sales|chart|note|text/i).closest("div.flex.h-full");
    expect(card?.className).toMatch(/shadow-\[var\(--elevation-1\)\]/);
  });
```

> If the existing harness exposes the wrapper more directly (e.g. a `data-testid`), use that instead. The assertion's intent: the wrapper carries `shadow-[var(--elevation-1)]`.

- [ ] **Step 2: Run it to verify it fails**

Run: `pnpm exec vitest run src/test/dashboardCardTile.test.tsx`
Expected: the new test FAILS (wrapper currently has `shadow-sm`).

- [ ] **Step 3: Polish the wrapper + header + loading skeleton**

In `frontend/src/components/dashboard/DashboardCardTile.tsx`, change ONLY the outer wrapper className (line ~68) from:

```tsx
    <div className="flex h-full flex-col rounded-xl border bg-card/70 p-4 shadow-sm">
```

to (glass + elevation token + hover-lift):

```tsx
    <div className="group/tile flex h-full flex-col rounded-xl border bg-card/70 p-4 shadow-[var(--elevation-1)] transition-shadow hover:shadow-[var(--elevation-3)]">
```

And in `ChartTileBody`, replace the bare loading spinner (the `isLoading` branch, ~lines 247–250) with a skeleton for smoother perceived loading:

```tsx
      {isLoading ? (
        <div className="h-56 w-full animate-pulse rounded-md bg-muted/50" />
      ) : data && data.row_count > 0 ? (
```

(Keep the `Spinner` import only if still used elsewhere in the file; if it becomes unused, remove the import to keep lint clean.)

- [ ] **Step 4: Run the dashboard tile + related suites**

Run: `pnpm exec vitest run src/test/dashboardCardTile.test.tsx src/test/dashboardDetailFilters.test.tsx`
Expected: PASS (the chrome test + existing tile tests; the `isLoading` skeleton is only shown when `useChartData` reports loading, which these tests don't, so existing assertions are unaffected).

- [ ] **Step 5: Type check + lint**

Run: `pnpm exec tsc --noEmit && pnpm lint`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/dashboard/DashboardCardTile.tsx frontend/src/test/dashboardCardTile.test.tsx
git commit -m "style(dashboard): tile chrome (elevation + hover-lift) + chart loading skeleton"
```

---

### Task 4: Docs + full gate + prod build (controller-executed)

**Files:**
- Modify: `docs/FRONTEND.md`

> **Controller note:** `docs/FRONTEND.md` is in the user's WIP. Controller stashes it, edits, commits, pops — as in slices 1–6. (Only the user's stale tab-split `/build` row is in the stash from slice 6; check for conflicts on pop.)

- [ ] **Step 1: Update the docs**

In `docs/FRONTEND.md`, update the `/dashboards/:dashboardId` row and the "Dashboards" section to describe the command-center layout: native filters now in a **horizontal top filter-bar** (was a left drawer), a **full-width gridstack canvas**, and polished tile chrome. Keep the cross-filter / drill / native-filter behavior wording accurate (unchanged).

- [ ] **Step 2: Run the FULL gate first-hand**

Run: `pnpm exec tsc --noEmit` → PASS.
Run: `pnpm lint` → PASS (0 errors; warnings unchanged from 44 baseline).
Run: `pnpm test` → PASS — all suites, including the new `dashboardFilterBar` + the chrome assertion.
Run: `pnpm build` → succeeds.

- [ ] **Step 3: Commit**

```bash
git add docs/FRONTEND.md
git commit -m "docs(frontend): dashboard command-center (top filter-bar + full-width canvas)"
```

- [ ] **Step 4: Record the manual smoke for the user**

Tell the user to smoke in a browser (needs backend + a dashboard with tiles + native filters): the top filter-bar renders + filtering updates tiles; cross-filter (click a chart point) still works; tiles show the hover-lift; gridstack drag/resize/persist still works in edit mode; responsive (bar wraps, canvas reflows).

---

## Self-Review

**Spec coverage:**
- New horizontal `DashboardFilterBar` reusing controls + cascading + selection/edit → Task 1. ✓
- `DashboardDetail` top-bar + full-width canvas; drawer removed → Task 2. ✓
- `DashboardCardTile` chrome (elevation + hover-lift) + chart loading skeleton → Task 3. ✓
- Docs + full gate + build + manual smoke → Task 4. ✓
- Off-limits respected (gridstack engine, dialog.tsx, filter-control logic, chart/drill/cross-filter) → not modified by any task. ✓
- Out of scope (focus/TV mode, new filter caps) → untouched. ✓

**Placeholder scan:** No TBD/TODO. Task 1 gives the full bar code; Task 2 the exact layout swap + a delete guarded by grep; Task 3 the exact chrome + skeleton edits (with a note to adapt the chrome assertion to the existing tile-test harness — concrete intent, not vague). Layout/gridstack visuals are explicitly a manual smoke, stated.

**Type consistency:**
- `DashboardFilterBar` `Props` = the drawer's `Props` exactly (`filters`/`selections`/`onSelectionChange`/`onClearAll`/`editing`/`onAddFilter?`/`onEditFilter?`); control props match their components (`ValueFilterControl({filter,values,onChange,constraints,enabled})`, `TimeFilterControl({value,onChange,label})`, `NumericFilterControl({min,max,onChange,label})`). ✓
- `parentConstraints` moved into the bar (was in the drawer); same signature. ✓
- Adoption marker for tile chrome: `shadow-[var(--elevation-1)]` matches the token. ✓
- Preserved handles: filter label text, "Clear all", "Add filter", "Edit {label}", control aria-labels → all in the bar. ✓

No gaps found.
