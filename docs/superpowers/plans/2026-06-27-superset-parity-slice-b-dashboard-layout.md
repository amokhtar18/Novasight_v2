# Slice B — Dashboard layout (free resizable grid) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the dashboard from a reorder-only grid into a true 12-column **free resizable grid** (drag to move via `x`/`y`, drag to resize via `w`/`h`, variable height), using the `x/y/w/h` the tile model already stores, with a keyboard-accessible size fallback.

**Architecture:** Adopt **gridstack** (React-19-safe; no `findDOMNode`) behind the `DashboardGrid` boundary using the "React renders the items, gridstack adopts them" pattern — tile content (`DashboardCardTile` with its chart/drill/cross-filter) stays ordinary React. Persistence reuses the existing `PUT /dashboards/{id}/layout` endpoint (no backend change): gridstack's `change` event → `{id,x,y,w,h}` + a row-major `position` → optimistic cache update + `setLayout.mutate`, debounced.

**Tech Stack:** React 19 + TypeScript + Vite, `gridstack` (new dep), TanStack Query, Vitest/RTL. Frontend-only slice.

## Global Constraints

- **Golden rule #1 (no hardcoded config):** grid constants (`column=12`, `cellHeight`, `margin`, the mobile breakpoint) are frontend **display** constants — fine in code. Add **no** new settings/env/tenant config.
- **Golden rule #3 (grounded/read-only):** pure layout/display slice. No query, data-path, or tenancy change. Cross-filter and drill keep using the governed semantic paths unchanged.
- **Golden rule #4 (thin slice):** the free resizable grid only. **Out of scope:** tabs, nested row/column containers, per-tile styling, fullscreen, per-breakpoint *persisted* layouts, undo/redo.
- **Golden rule #5 (done = tested + typed + documented):** every task ends green on `cd frontend && pnpm exec tsc --noEmit && pnpm lint && pnpm test`. The slice updates `docs/DASHBOARDS.md`.
- **No backend change.** The `DashboardTile` model and `PUT /dashboards/{id}/layout` already accept `{id, position, x, y, w, h}`.
- **Encoding contract (existing, do not change):** layout persistence uses `TileLayout { id: string; position: number; x?: number; y?: number; w?: number; h?: number }` and `DashboardLayoutUpdate { tiles: TileLayout[] }`.
- **Toolchain:** run all commands from `frontend/`. gridstack is **mocked** in component tests (jsdom can't drag/resize) — the *real* gridstack integration is validated by the manual smoke in Final Verification.

---

## File structure

**New**
- `frontend/src/lib/dashboardLayout.ts` — pure mapping: gridstack saved nodes → `TileLayout[]` with row-major `position`.
- `frontend/src/components/dashboard/TileSizeControl.tsx` — keyboard-accessible width/height control (the a11y fallback for drag-resize).
- `frontend/src/test/dashboardLayout.test.ts` — pure mapping tests.
- `frontend/src/test/dashboardGrid.test.tsx` — gridstack-mocked integration tests for `DashboardGrid`.
- `frontend/src/test/tileSizeControl.test.tsx` — a11y control tests.

**Modify**
- `frontend/package.json` — add `gridstack`.
- `frontend/src/main.tsx` — import `gridstack/dist/gridstack.css` (global; keeps CSS out of component tests).
- `frontend/src/components/dashboard/DashboardGrid.tsx` — replace dnd-kit with gridstack; expose `resizeTile`.
- `frontend/src/components/dashboard/DashboardCardTile.tsx` — drop dnd-kit `useSortable` + `spanForW`/`SIZE_TO_W`/`sizeFromW` + the size `<Select>`; fill height; grip becomes gridstack's `.tile-drag-handle`; render `TileSizeControl` in edit mode.
- `frontend/src/pages/DashboardDetail.tsx` — update the edit-mode hint copy.
- `frontend/src/test/setup.ts` — add `ResizeObserver` + `matchMedia` jsdom polyfills.
- `frontend/src/test/dashboardCardTile.test.tsx` — drop the now-unused dnd-kit mocks; keep the rest.
- `frontend/src/test/dashboardDetailFilters.test.tsx` — replace the dnd-kit mocks with a gridstack mock.
- `docs/DASHBOARDS.md` — add a "Dashboard layout" section.

---

## Task 1: Pure layout-mapping helper + jsdom test polyfills

**Files:**
- Create: `frontend/src/lib/dashboardLayout.ts`
- Create (test): `frontend/src/test/dashboardLayout.test.ts`
- Modify: `frontend/src/test/setup.ts`

**Interfaces:**
- Consumes: existing `TileLayout` from `@/types/api`.
- Produces: `GridLayoutNode` interface and `nodesToLayoutTiles(nodes: GridLayoutNode[]): TileLayout[]` — used by `DashboardGrid` (Task 2) to map gridstack's `grid.save(false)` output to the layout payload.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/test/dashboardLayout.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { nodesToLayoutTiles } from "@/lib/dashboardLayout";

describe("nodesToLayoutTiles", () => {
  it("maps gridstack nodes to TileLayout with row-major position (y then x)", () => {
    // Out of visual order on purpose: bottom-left, top-right, top-left.
    const tiles = nodesToLayoutTiles([
      { id: "c", x: 0, y: 4, w: 6, h: 4 },
      { id: "b", x: 6, y: 0, w: 6, h: 4 },
      { id: "a", x: 0, y: 0, w: 6, h: 4 },
    ]);
    expect(tiles.map((t) => t.id)).toEqual(["a", "b", "c"]); // (0,0),(6,0),(0,4)
    expect(tiles.map((t) => t.position)).toEqual([0, 1, 2]);
    expect(tiles[0]).toEqual({ id: "a", position: 0, x: 0, y: 0, w: 6, h: 4 });
  });

  it("defaults missing geometry and drops nodes without a string id", () => {
    const tiles = nodesToLayoutTiles([
      { id: "a" },
      { id: undefined, x: 1, y: 1 },
      { x: 2, y: 2 },
    ]);
    expect(tiles).toEqual([{ id: "a", position: 0, x: 0, y: 0, w: 1, h: 1 }]);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && pnpm exec vitest run src/test/dashboardLayout.test.ts`
Expected: FAIL — `@/lib/dashboardLayout` does not exist (import error).

- [ ] **Step 3: Implement the helper**

Create `frontend/src/lib/dashboardLayout.ts`:

```ts
import type { TileLayout } from "@/types/api";

/** The geometry subset of a gridstack node/widget that we persist. */
export interface GridLayoutNode {
  id?: string | number | null;
  x?: number;
  y?: number;
  w?: number;
  h?: number;
}

/**
 * Map gridstack's saved nodes to the dashboard layout payload. `position` is
 * derived row-major (top-to-bottom, then left-to-right) so the server's
 * position-ordered reads stay coherent with the visual grid. Nodes without a
 * non-empty string id (the tile id we set via `gs-id`) are dropped.
 */
export function nodesToLayoutTiles(nodes: GridLayoutNode[]): TileLayout[] {
  return nodes
    .filter((n): n is GridLayoutNode & { id: string } => typeof n.id === "string" && n.id.length > 0)
    .slice()
    .sort((a, b) => (a.y ?? 0) - (b.y ?? 0) || (a.x ?? 0) - (b.x ?? 0))
    .map((n, i) => ({
      id: n.id,
      position: i,
      x: n.x ?? 0,
      y: n.y ?? 0,
      w: n.w ?? 1,
      h: n.h ?? 1,
    }));
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && pnpm exec vitest run src/test/dashboardLayout.test.ts`
Expected: PASS.

- [ ] **Step 5: Add jsdom polyfills for gridstack-based components**

gridstack (and ECharts) use `ResizeObserver` and `matchMedia`, which jsdom does not implement. Add minimal no-op polyfills to `frontend/src/test/setup.ts` so any gridstack-touching test does not throw. Replace the file contents with:

```ts
/**
 * Vitest global test setup.
 * Imported via vitest.config.ts setupFiles.
 */
import "@testing-library/jest-dom";

// jsdom has no ResizeObserver (used by gridstack + ECharts) — provide a no-op.
if (!("ResizeObserver" in globalThis)) {
  class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  }
  globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;
}

// jsdom has no matchMedia (used by gridstack responsive column logic) — stub it.
if (!globalThis.matchMedia) {
  globalThis.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof globalThis.matchMedia;
}
```

- [ ] **Step 6: Run the full frontend suite (no regressions from the setup change)**

Run: `cd frontend && pnpm exec tsc --noEmit && pnpm lint && pnpm test`
Expected: all pass (the polyfills are additive; the existing suite stays green).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/dashboardLayout.ts frontend/src/test/dashboardLayout.test.ts frontend/src/test/setup.ts
git commit -m "feat(dashboard): layout-mapping helper + jsdom polyfills for gridstack (Slice B Task 1)"
```

---

## Task 2: gridstack engine swap (DashboardGrid + DashboardCardTile)

This is the core: replace dnd-kit reorder with gridstack free drag/resize. `DashboardGrid` and `DashboardCardTile`'s dnd-kit removal must land together (the tile's `useSortable` requires the grid's `DndContext`), so they are one task.

**Files:**
- Modify: `frontend/package.json` (add `gridstack`)
- Modify: `frontend/src/main.tsx` (global CSS import)
- Modify: `frontend/src/components/dashboard/DashboardGrid.tsx`
- Modify: `frontend/src/components/dashboard/DashboardCardTile.tsx`
- Create (test): `frontend/src/test/dashboardGrid.test.tsx`
- Modify (test): `frontend/src/test/dashboardCardTile.test.tsx`
- Modify (test): `frontend/src/test/dashboardDetailFilters.test.tsx`

**Interfaces:**
- Consumes: `nodesToLayoutTiles` (Task 1); existing `useSetDashboardLayout`, `queryKeys.dashboard`, `useUpdateDashboardTile`, `useDeleteDashboardTile`; `DashboardTileRead`, `DashboardRead`, `TileLayout`.
- Produces: `DashboardGrid` rendering `.grid-stack`/`.grid-stack-item` with `gs-*` attrs; gridstack init/teardown; debounced `change`→`setLayout`. `DashboardCardTile` no longer uses dnd-kit; its grip carries class `tile-drag-handle`.

- [ ] **Step 1: Install gridstack**

Run: `cd frontend && pnpm add gridstack`
Then import its CSS globally — in `frontend/src/main.tsx`, add this line next to the existing global style import(s):

```ts
import "gridstack/dist/gridstack.css";
```

- [ ] **Step 2: Write the failing test for DashboardGrid**

Create `frontend/src/test/dashboardGrid.test.tsx`. It mocks gridstack (a controllable stub) and the layout hook, stubs the tile, and asserts the integration seams.

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { DashboardTileRead } from "@/types/api";

// Capture the gridstack stub + its event handlers so tests can drive "change".
const { gridStub, handlers, initSpy } = vi.hoisted(() => {
  const handlers: Record<string, (...a: unknown[]) => void> = {};
  const gridStub = {
    on: vi.fn((evt: string, cb: (...a: unknown[]) => void) => {
      handlers[evt] = cb;
    }),
    off: vi.fn(),
    save: vi.fn(() => [{ id: "t1", x: 0, y: 0, w: 6, h: 4 }]),
    destroy: vi.fn(),
    enableMove: vi.fn(),
    enableResize: vi.fn(),
    update: vi.fn(),
  };
  const initSpy = vi.fn(() => gridStub);
  return { gridStub, handlers, initSpy };
});

vi.mock("gridstack", () => ({ GridStack: { init: initSpy } }));

const mutate = vi.fn();
// Mock the whole hooks module so the real api client isn't imported. DashboardGrid
// only uses `useSetDashboardLayout` and `queryKeys.dashboard` from here.
vi.mock("@/api/hooks", () => ({
  useSetDashboardLayout: () => ({ mutate }),
  queryKeys: { dashboard: (id: string) => ["dashboards", id] as const },
}));

// Keep the test focused on grid wiring — stub the tile.
vi.mock("@/components/dashboard/DashboardCardTile", () => ({
  DashboardCardTile: ({ tile }: { tile: DashboardTileRead }) => (
    <div data-testid={`tile-${tile.id}`}>{tile.title}</div>
  ),
}));

import { DashboardGrid } from "@/components/dashboard/DashboardGrid";

function tile(id: string, x: number, y: number): DashboardTileRead {
  return {
    id, kind: "chart", chart_id: "c", content: null, title: id,
    position: 0, x, y, w: 6, h: 4, chart: null,
  };
}

function wrap(editing: boolean) {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <DashboardGrid
        tiles={[tile("t1", 0, 0)]}
        dashboardId="dash-1"
        editing={editing}
        filters={[]}
        selections={{}}
        crossFilter={[]}
      />
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  for (const k of Object.keys(handlers)) delete handlers[k];
});

describe("DashboardGrid (gridstack)", () => {
  it("renders each tile as a .grid-stack-item with gs-* attributes", () => {
    wrap(false);
    const item = screen.getByTestId("tile-t1").closest(".grid-stack-item");
    expect(item).not.toBeNull();
    expect(item).toHaveAttribute("gs-id", "t1");
    expect(item).toHaveAttribute("gs-w", "6");
  });

  it("initializes gridstack with a 12-column grid", () => {
    wrap(false);
    expect(initSpy).toHaveBeenCalledTimes(1);
    expect(initSpy.mock.calls[0][0]).toMatchObject({ column: 12 });
  });

  it("enables drag/resize in edit mode and disables in view mode", () => {
    wrap(true);
    expect(gridStub.enableMove).toHaveBeenLastCalledWith(true);
    expect(gridStub.enableResize).toHaveBeenLastCalledWith(true);
  });

  it("persists the mapped layout (debounced) on a gridstack change", () => {
    vi.useFakeTimers();
    wrap(true);
    act(() => {
      handlers["change"]?.();
      vi.advanceTimersByTime(500);
    });
    expect(mutate).toHaveBeenCalledWith({
      tiles: [{ id: "t1", position: 0, x: 0, y: 0, w: 6, h: 4 }],
    });
    vi.useRealTimers();
  });

  it("tears down gridstack on unmount", () => {
    const { unmount } = wrap(false);
    unmount();
    expect(gridStub.destroy).toHaveBeenCalled();
  });
});
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd frontend && pnpm exec vitest run src/test/dashboardGrid.test.tsx`
Expected: FAIL — `DashboardGrid` still uses dnd-kit and renders no `.grid-stack-item`/gs-* attrs; `GridStack.init` is never called.

- [ ] **Step 4: Rewrite `DashboardGrid` to use gridstack**

Replace the entire contents of `frontend/src/components/dashboard/DashboardGrid.tsx` with:

```tsx
/**
 * DashboardGrid — a free 12-column resizable grid of tiles (gridstack).
 *
 * React renders the `.grid-stack` items (carrying the tile's gs-x/y/w/h) and a
 * `useEffect` initializes gridstack, which adopts them as draggable/resizable
 * widgets. Tile content stays ordinary React. On a layout change gridstack's
 * geometry is mapped to the existing `PUT /dashboards/{id}/layout` payload
 * (debounced + optimistic). Drag/resize are enabled only in edit mode.
 */

import { useEffect, useRef, type HTMLAttributes } from "react";
import { GridStack } from "gridstack";

import { useQueryClient } from "@tanstack/react-query";

import { queryKeys, useSetDashboardLayout } from "@/api/hooks";
import { DashboardCardTile } from "./DashboardCardTile";
import { nodesToLayoutTiles, type GridLayoutNode } from "@/lib/dashboardLayout";
import type { FilterSelections } from "@/lib/dashboardFilters";
import type {
  DashboardRead,
  DashboardTileRead,
  NativeFilter,
  SemanticFilter,
  SelectionPair,
} from "@/types/api";

const GRID_COLUMNS = 12;
const GRID_CELL_HEIGHT = 64; // px per row unit
const GRID_MARGIN = 8; // px gutter
const GRID_MOBILE_BREAKPOINT = 768; // collapse to one column below this width
const SAVE_DEBOUNCE_MS = 400;

interface DashboardGridProps {
  tiles: DashboardTileRead[];
  dashboardId: string;
  editing: boolean;
  filters: NativeFilter[];
  selections: FilterSelections;
  crossFilter: SemanticFilter[];
  onCrossFilter?: (pairs: SelectionPair[]) => void;
}

/** gridstack reads geometry from these attributes when it adopts the DOM items. */
function gsItemAttrs(tile: DashboardTileRead) {
  return {
    "gs-id": tile.id,
    "gs-x": tile.x,
    "gs-y": tile.y,
    "gs-w": tile.w,
    "gs-h": tile.h,
  } as unknown as HTMLAttributes<HTMLDivElement>;
}

export function DashboardGrid({
  tiles,
  dashboardId,
  editing,
  filters,
  selections,
  crossFilter,
  onCrossFilter,
}: DashboardGridProps) {
  const queryClient = useQueryClient();
  const setLayout = useSetDashboardLayout(dashboardId);
  const elRef = useRef<HTMLDivElement>(null);
  const gridRef = useRef<GridStack | null>(null);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Re-init gridstack only when the tile SET changes (add/remove) — not on
  // drag/resize or data refresh. A changing key would remount; instead we key
  // the effect on the joined ids.
  const tileIds = tiles.map((t) => t.id).join(",");

  // The once-bound change handler reads current values through this ref.
  const persistRef = useRef<() => void>(() => {});
  persistRef.current = () => {
    const grid = gridRef.current;
    if (!grid) return;
    const layoutTiles = nodesToLayoutTiles(grid.save(false) as GridLayoutNode[]);
    queryClient.setQueryData<DashboardRead>(queryKeys.dashboard(dashboardId), (old) => {
      if (!old) return old;
      const byId = new Map(layoutTiles.map((l) => [l.id, l]));
      return {
        ...old,
        tiles: old.tiles.map((t) => {
          const l = byId.get(t.id);
          return l
            ? { ...t, position: l.position, x: l.x ?? t.x, y: l.y ?? t.y, w: l.w ?? t.w, h: l.h ?? t.h }
            : t;
        }),
      };
    });
    setLayout.mutate({ tiles: layoutTiles });
  };

  /** Resize one tile through gridstack (the keyboard a11y control calls this in Task 3). */
  function resizeTile(tileId: string, w: number, h: number) {
    const grid = gridRef.current;
    const el = elRef.current?.querySelector<HTMLElement>(`[gs-id="${CSS.escape(tileId)}"]`);
    if (grid && el) grid.update(el, { w, h }); // fires "change" → debounced persist
  }
  // resizeTile is consumed by DashboardCardTile in Task 3; referenced to avoid an unused warning.
  void resizeTile;

  useEffect(() => {
    if (!elRef.current) return;
    const grid = GridStack.init(
      {
        column: GRID_COLUMNS,
        cellHeight: GRID_CELL_HEIGHT,
        margin: GRID_MARGIN,
        float: false,
        handle: ".tile-drag-handle",
        disableDrag: !editing,
        disableResize: !editing,
        columnOpts: { breakpoints: [{ w: GRID_MOBILE_BREAKPOINT, c: 1 }], breakpointForWindow: true },
      },
      elRef.current
    );
    gridRef.current = grid;
    grid.on("change", () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
      saveTimer.current = setTimeout(() => persistRef.current(), SAVE_DEBOUNCE_MS);
    });
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
      grid.off("change");
      grid.destroy(false);
      gridRef.current = null;
    };
    // Re-init only when the tile set changes; `editing` is synced by the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tileIds]);

  // Toggle drag/resize on edit-mode change without re-initializing.
  useEffect(() => {
    const grid = gridRef.current;
    if (!grid) return;
    grid.enableMove(editing);
    grid.enableResize(editing);
  }, [editing]);

  return (
    <div ref={elRef} className="grid-stack">
      {tiles.map((tile) => (
        <div key={tile.id} className="grid-stack-item" {...gsItemAttrs(tile)}>
          <div className="grid-stack-item-content">
            <DashboardCardTile
              tile={tile}
              dashboardId={dashboardId}
              editing={editing}
              filters={filters}
              selections={selections}
              crossFilter={crossFilter}
              onCrossFilter={onCrossFilter}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 5: Strip dnd-kit + the size dropdown from `DashboardCardTile`**

In `frontend/src/components/dashboard/DashboardCardTile.tsx`:

1. Remove the imports `useSortable` (`@dnd-kit/sortable`) and `CSS` (`@dnd-kit/utilities`).
2. Delete the `TileSize` type, `SIZE_TO_W`, `sizeFromW`, and `spanForW`.
3. In `DashboardCardTile`, delete the `useSortable(...)` call and the `style` object.
4. Replace the outer wrapper `<div ref={setNodeRef} style={style} className={cn("flex flex-col rounded-xl border bg-card/70 p-4 shadow-sm", spanForW(tile.w), isDragging && "...")}>` with a height-filling container (gridstack owns position/size now):

```tsx
    <div className="flex h-full flex-col rounded-xl border bg-card/70 p-4 shadow-sm">
```

5. Change the grip `<button>` so it is gridstack's drag handle: add the class `tile-drag-handle` and drop the dnd-kit `{...attributes} {...listeners}`:

```tsx
        {editing && (
          <button
            type="button"
            className="tile-drag-handle cursor-grab touch-none rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground active:cursor-grabbing"
            aria-label={`Drag ${title}`}
          >
            <GripVertical className="h-4 w-4" />
          </button>
        )}
```

6. Delete the size `<Select>` block (the `aria-label={`Size of ${title}`}` dropdown and its `<option>`s) entirely. Keep the remove `<button>`. (Task 3 adds the keyboard size control here.)
7. Remove the now-unused `Select` import if nothing else in the file uses it.
8. Make the chart body fill its tile so it resizes with the grid: in `ChartTileBody`, change the `<ChartRenderer … className="h-64" … />` to `className="h-full"`, and change the wrapper around it from `<div className="relative h-full">` (already `h-full`) — confirm the loading branch container height does not force a fixed height (leave the spinner branch as-is; only the rendered-chart `ChartRenderer` height changes from `h-64` → `h-full`).

- [ ] **Step 6: Update the two existing tests for the engine swap**

In `frontend/src/test/dashboardCardTile.test.tsx`, delete the now-unused dnd-kit mocks (the component no longer imports them):

```tsx
// DELETE these two blocks:
vi.mock("@dnd-kit/sortable", () => ({ useSortable: () => ({ /* … */ }) }));
vi.mock("@dnd-kit/utilities", () => ({ CSS: { Transform: { toString: () => "" } } }));
```

In `frontend/src/test/dashboardDetailFilters.test.tsx`, replace the three dnd-kit mocks (the `@dnd-kit/core`, `@dnd-kit/sortable`, `@dnd-kit/utilities` blocks around lines 71–94) with a single gridstack mock so `GridStack.init` does not run real DOM code:

```tsx
// gridstack stub — DashboardGrid initializes it; it must be inert in JSDOM.
vi.mock("gridstack", () => ({
  GridStack: {
    init: () => ({
      on: () => {}, off: () => {}, save: () => [], destroy: () => {},
      enableMove: () => {}, enableResize: () => {}, update: () => {},
    }),
  },
}));
```

Leave the `useSetDashboardLayout: () => ({ mutate: vi.fn() })` mock and the rest of that file unchanged.

- [ ] **Step 7: Run the new + updated tests to verify they pass**

Run: `cd frontend && pnpm exec vitest run src/test/dashboardGrid.test.tsx src/test/dashboardCardTile.test.tsx src/test/dashboardDetailFilters.test.tsx`
Expected: PASS (grid seams, tile wiring, and the cross-filter integration test all green).

- [ ] **Step 8: Run the full frontend gate**

Run: `cd frontend && pnpm exec tsc --noEmit && pnpm lint && pnpm test`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add frontend/package.json frontend/pnpm-lock.yaml frontend/src/main.tsx frontend/src/components/dashboard/DashboardGrid.tsx frontend/src/components/dashboard/DashboardCardTile.tsx frontend/src/test/dashboardGrid.test.tsx frontend/src/test/dashboardCardTile.test.tsx frontend/src/test/dashboardDetailFilters.test.tsx
git commit -m "feat(dashboard): free resizable grid via gridstack (replaces dnd-kit reorder) (Slice B Task 2)"
```

---

## Task 3: Keyboard-accessible size control (a11y fallback)

gridstack drag/resize is pointer-only. Add a keyboard-operable width/height control per tile (edit mode), routed through gridstack so it uses the same persist path as a drag.

**Files:**
- Create: `frontend/src/components/dashboard/TileSizeControl.tsx`
- Create (test): `frontend/src/test/tileSizeControl.test.tsx`
- Modify: `frontend/src/components/dashboard/DashboardGrid.tsx` (pass `onResizeTile` down)
- Modify: `frontend/src/components/dashboard/DashboardCardTile.tsx` (accept `onResizeTile`, render the control)

**Interfaces:**
- Consumes: `resizeTile(tileId, w, h)` from `DashboardGrid` (Task 2).
- Produces: `TileSizeControl` props `{ title: string; w: number; h: number; onResize: (w: number, h: number) => void }`; `DashboardCardTile` prop `onResizeTile?: (tileId: string, w: number, h: number) => void`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/test/tileSizeControl.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { TileSizeControl } from "@/components/dashboard/TileSizeControl";

describe("TileSizeControl", () => {
  it("opens via a keyboard-focusable button and emits new width/height", () => {
    const onResize = vi.fn();
    render(<TileSizeControl title="Revenue" w={6} h={4} onResize={onResize} />);

    fireEvent.click(screen.getByRole("button", { name: "Size of Revenue" }));
    fireEvent.change(screen.getByLabelText("Width of Revenue"), { target: { value: "8" } });
    expect(onResize).toHaveBeenCalledWith(8, 4);

    fireEvent.change(screen.getByLabelText("Height of Revenue"), { target: { value: "5" } });
    expect(onResize).toHaveBeenCalledWith(6, 5);
  });

  it("clamps out-of-range values to 1..12", () => {
    const onResize = vi.fn();
    render(<TileSizeControl title="Revenue" w={6} h={4} onResize={onResize} />);
    fireEvent.click(screen.getByRole("button", { name: "Size of Revenue" }));
    fireEvent.change(screen.getByLabelText("Width of Revenue"), { target: { value: "99" } });
    expect(onResize).toHaveBeenCalledWith(12, 4);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && pnpm exec vitest run src/test/tileSizeControl.test.tsx`
Expected: FAIL — `TileSizeControl` does not exist.

- [ ] **Step 3: Implement `TileSizeControl`**

Create `frontend/src/components/dashboard/TileSizeControl.tsx`:

```tsx
/**
 * TileSizeControl — keyboard-accessible width/height control for a tile (edit
 * mode). The accessibility fallback for pointer-only gridstack drag-resize: it
 * emits the new size through `onResize`, which the grid applies via gridstack
 * (same persist path as a drag). Full keyboard-drag is a known gridstack limit.
 */
import { useEffect, useRef, useState } from "react";
import { Maximize2 } from "lucide-react";

const MIN = 1;
const MAX = 12;

function clamp(v: number): number {
  const n = Math.round(v);
  if (Number.isNaN(n)) return MIN;
  return Math.max(MIN, Math.min(MAX, n));
}

export function TileSizeControl({
  title,
  w,
  h,
  onResize,
}: {
  title: string;
  w: number;
  h: number;
  onResize: (w: number, h: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onClick);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onClick);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-label={`Size of ${title}`}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
      >
        <Maximize2 className="h-4 w-4" />
      </button>
      {open && (
        <div className="absolute right-0 z-20 mt-1 w-44 space-y-2 rounded-md border bg-popover p-3 text-popover-foreground shadow-md">
          <label className="flex items-center justify-between gap-2 text-xs">
            Width
            <input
              type="number"
              min={MIN}
              max={MAX}
              value={w}
              aria-label={`Width of ${title}`}
              onChange={(e) => onResize(clamp(Number(e.target.value)), h)}
              className="h-7 w-16 rounded border bg-transparent px-2 text-right text-sm"
            />
          </label>
          <label className="flex items-center justify-between gap-2 text-xs">
            Height
            <input
              type="number"
              min={MIN}
              max={MAX}
              value={h}
              aria-label={`Height of ${title}`}
              onChange={(e) => onResize(w, clamp(Number(e.target.value)))}
              className="h-7 w-16 rounded border bg-transparent px-2 text-right text-sm"
            />
          </label>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && pnpm exec vitest run src/test/tileSizeControl.test.tsx`
Expected: PASS.

- [ ] **Step 5: Thread the resize callback through the grid and tile**

In `frontend/src/components/dashboard/DashboardGrid.tsx`:
- Remove the `void resizeTile;` line.
- Pass the callback to the tile in the render: add `onResizeTile={resizeTile}` to `<DashboardCardTile … />`.

In `frontend/src/components/dashboard/DashboardCardTile.tsx`:
- Import the control: `import { TileSizeControl } from "./TileSizeControl";`
- Add `onResizeTile?: (tileId: string, w: number, h: number) => void;` to `TileProps` and destructure it in `DashboardCardTile`.
- In edit mode, render the control next to the remove button (where the size `<Select>` used to be):

```tsx
        {editing && (
          <>
            <TileSizeControl
              title={title}
              w={tile.w}
              h={tile.h}
              onResize={(w, h) => onResizeTile?.(tile.id, w, h)}
            />
            <button
              type="button"
              onClick={() => deleteTile.mutate(tile.id)}
              aria-label={`Remove ${title}`}
              className="rounded p-1 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </>
        )}
```

- [ ] **Step 6: Run tsc + lint + the affected suites**

Run: `cd frontend && pnpm exec tsc --noEmit && pnpm lint && pnpm exec vitest run src/test/tileSizeControl.test.tsx src/test/dashboardGrid.test.tsx src/test/dashboardCardTile.test.tsx`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/dashboard/TileSizeControl.tsx frontend/src/test/tileSizeControl.test.tsx frontend/src/components/dashboard/DashboardGrid.tsx frontend/src/components/dashboard/DashboardCardTile.tsx
git commit -m "feat(dashboard): keyboard-accessible tile size control (a11y fallback) (Slice B Task 3)"
```

---

## Task 4: Edit-mode copy + docs + whole-slice gate

**Files:**
- Modify: `frontend/src/pages/DashboardDetail.tsx`
- Modify: `docs/DASHBOARDS.md`

- [ ] **Step 1: Update the edit-mode hint copy**

In `frontend/src/pages/DashboardDetail.tsx`, replace the edit-mode hint text:

```tsx
      {editing && (
        <Badge variant="info" className="mb-4">
          Drag tiles to move · drag a tile's edge to resize · use the size control or remove
        </Badge>
      )}
```

- [ ] **Step 2: Document the layout in `docs/DASHBOARDS.md`**

Append a new section to `docs/DASHBOARDS.md`:

```markdown
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
```

- [ ] **Step 3: Run the full frontend gate**

Run: `cd frontend && pnpm exec tsc --noEmit && pnpm lint && pnpm test`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/DashboardDetail.tsx docs/DASHBOARDS.md
git commit -m "docs(dashboard): layout edit-mode copy + DASHBOARDS layout section (Slice B Task 4)"
```

---

## Final verification (whole slice)

- [ ] **Frontend gate:** `cd frontend && pnpm exec tsc --noEmit && pnpm lint && pnpm test` — all pass.
- [ ] **Backend untouched:** confirm no backend files changed in the slice (`git diff --stat <slice-base>..HEAD -- backend/` is empty). No backend gate needed.
- [ ] **Manual smoke (REQUIRED — gridstack is mocked in tests, so this is the only real validation of the integration):** run the app, open a dashboard with ≥2 tiles, toggle Edit; (a) drag a tile by its grip to a new position; (b) drag a tile edge to resize (confirm a chart redraws to the new size); (c) use the keyboard **Size** control to change width/height; (d) reload and confirm the new layout persisted; (e) view mode shows the saved layout with no drag handles; (f) narrow the window and confirm tiles stack toward one column.
- [ ] **Spec parity:** confirm every part of `docs/superpowers/specs/2026-06-27-superset-parity-slice-b-dashboard-layout-design.md` (Parts 1–7) maps to a committed task: Part 1 → Task 2 (+ Task 1 helper); Part 2 → Task 2; Part 3 → Tasks 1–2; Part 4 → Task 2 (`columnOpts`); Part 5 → Task 3; Part 6 → per-task tests; Part 7 → Task 4 + Global Constraints.
- [ ] **Progress log:** append a Slice B section to `.superpowers/sdd/progress.md` summarizing the tasks and the verified gate.

---

## Self-review notes (author)

- **Spec coverage:** engine/integration (Part 1) → Task 2 with the pure mapping seam in Task 1; tile geometry/rendering (Part 2) → Task 2; edit/view + persistence (Part 3) → Tasks 1–2; responsive single-layout + auto-stack (Part 4) → `columnOpts` in Task 2; a11y fallback (Part 5) → Task 3; testing (Part 6) → per-task Vitest seams (gridstack mocked) + the required manual smoke; golden rules + docs (Part 7) → Global Constraints + Task 4. No backend change (matches spec). No gaps.
- **Type consistency:** `nodesToLayoutTiles(nodes: GridLayoutNode[]): TileLayout[]`, `resizeTile(tileId, w, h)`, `DashboardCardTile` prop `onResizeTile?(tileId, w, h)`, `TileSizeControl` prop `onResize(w, h)`, and the gridstack stub surface (`on/off/save/destroy/enableMove/enableResize/update`) are used identically across tasks and tests.
- **Coupling note:** the dnd-kit→gridstack swap (DashboardGrid + DashboardCardTile) is one task because the tile's old `useSortable` requires the grid's `DndContext`; splitting would leave a non-compiling intermediate.
- **Testing honesty:** gridstack is mocked in jsdom (it cannot perform real drag/resize there), so component tests assert the wiring seams only. The real integration (drag, resize, persist, responsive) is validated by the REQUIRED manual smoke in Final Verification — this is called out so a reviewer does not mistake green unit tests for end-to-end proof.
- **Open follow-ups (from spec non-goals):** tabs, nested row/column containers, per-tile styling, fullscreen, per-breakpoint persisted layouts, undo/redo.
```
