# Design — Dashboard View Redesign: Top Filter-Bar Command Center

- **Date:** 2026-06-27
- **Status:** Approved (direction + layout); pending spec review + plan
- **Area:** `frontend/` — `DashboardDetail` page + dashboard filter presentation + tile chrome
- **Predecessors:** Slices 1–6 (hardened primitives/tokens + the Chart Builder redesign this reuses patterns from).
- **Golden rules:** #4 (thin slice, bounded risk), #5 (tested + typed + documented), #2/#3 (tenancy + grounded query paths unchanged — we only restyle/rearrange).

## Summary

Redesign the dashboard **view** (`/dashboards/:id`) into a **top filter-bar command center** (user-approved): native filters become a horizontal bar of controls across the top, the gridstack tile canvas goes **full-width** below it, the tiles get **polished chrome** (glass/elevation/hover-lift), and the header/toolbar is refined. Restructure + polish **reusing all logic** — the filter-control components, selection/cascading state, the gridstack grid, chart/drill/cross-filter wiring, and the dialogs are unchanged.

## Hard constraints (off-limits)

- **Gridstack engine** (`DashboardGrid` drag/resize/persist mechanics) — reuse as-is; do NOT re-engineer the grid.
- **`dialog.tsx`** — in the user's uncommitted WIP; `AddObjectDialog` uses it. Use the dialog, do **not** edit the primitive.
- **Filter-control logic** (`ValueFilterControl`/`TimeFilterControl`/`NumericFilterControl`, `resolveTileFilters`, cascading `parentConstraints`, `useChartData`) — reused unchanged.

## Problem (current state)

`DashboardDetail` renders a flex row: `DashboardFilterDrawer` (a left vertical `aside`, collapsible, shown when filters exist or in edit mode) + `DashboardGrid` (gridstack canvas, `flex-1`). Tiles (`DashboardCardTile`) are `rounded-xl border bg-card/70 p-4 shadow-sm`. It works, but the left drawer competes with the canvas, the tiles are flat, and view-vs-edit isn't visually distinct — it doesn't read as a premium analytics surface.

## Decisions (locked during brainstorming)

| Decision | Choice |
|----------|--------|
| Screen | Dashboard view (`/dashboards/:id`) |
| Aim | Restructure + polish, reuse logic |
| Layout | **Top filter-bar command center** (filters horizontal on top; full-width canvas below) — confirmed via inline mockups |
| Filter presentation | New `DashboardFilterBar` (horizontal) reusing the existing filter controls + cascading + selection callbacks; replaces the left `DashboardFilterDrawer` on the page |
| Tile chrome | Polish `DashboardCardTile`'s wrapper (glass surface, `--elevation-*`, hover-lift, header refinement); body/drill/cross-filter logic unchanged |
| Out of scope | Focus/"TV" presentation mode (option C); any gridstack-engine change; `dialog.tsx`; new filter capabilities |

## Architecture

- **New `frontend/src/components/dashboard/DashboardFilterBar.tsx`** — a horizontal bar that maps each `NativeFilter` to its control (`ValueFilterControl`/`TimeFilterControl`/`NumericFilterControl`) laid out inline (compact chips/popovers as the controls allow), preserving: `selections`/`onSelectionChange`/`onClearAll`, cascading via `parentConstraints` (lifted/shared from the drawer or a shared helper), the `editing` Add/Edit affordances (`onAddFilter`/`onEditFilter`), the required-selection hint, and a "Clear all" action. Same `Props` shape as `DashboardFilterDrawer`. The old `DashboardFilterDrawer` is replaced (removed from the page; file deleted or left unused — plan decides).
- **`DashboardDetail` shell** — replace the `flex gap-4` (drawer + canvas) with a vertical stack: the refined header, the `DashboardFilterBar` (when filters exist or editing), then the **full-width** `DashboardGrid`. The edit-mode badge + filter "X active / Clear" summary live in/under the header. All filter state + handlers (`selections`, `crossFilter`, `saveFilter`, `removeFilter`, `handleCrossFilter`, seeding) are unchanged.
- **`DashboardCardTile` chrome** — restyle the outer wrapper (`glass`/`bg-card/70` + `shadow-[var(--elevation-1)]` → hover `shadow-[var(--elevation-3)]` lift via transition; cleaner header row). The `TileBody`/`ChartTileBody`/drill/cross-filter/`useChartData` logic is untouched. A chart-tile **loading skeleton** replaces the bare spinner where it improves perceived performance.
- **Tokens/polish:** hardened primitives + `--elevation-*`; `animate-in-up`; consistent spacing.

## Testing strategy (Vitest + RTL)

- **Reused filter logic is the safety net:** the existing dashboard suites (`dashboardDetailFilters.test.tsx`, `cascadingFilters.test.tsx`, `dashboardCardTile.test.tsx`, `dashboardGrid.test.tsx`, `nativeFilterEditor.test.tsx`) must stay green. They drive filters by control `aria-label`/role + the "Clear all"/"Add filter"/"Edit {filter}" buttons, all preserved by the bar. Any test that asserts the **drawer-specific** structure (e.g. the "Collapse/Expand filters" toggle, the left `aside`) is **rewritten** for the bar — not weakened.
- **New `DashboardFilterBar` test:** renders filters as a horizontal bar; a selection change calls `onSelectionChange`; "Clear all" calls `onClearAll`; edit mode shows Add/Edit; cascading constraints flow to a child control.
- **Tile chrome is styling-only:** `dashboardCardTile.test.tsx` queries by role/label (title, drag handle, remove, size control) — preserved.
- **Not jsdom-testable:** the gridstack canvas drag/resize, the full-width visual layout, and hover-lift — verified by `pnpm build` + a **manual browser smoke** (user step).

## Scope decomposition (tasks)

1. **`DashboardFilterBar`** (new, horizontal) reusing the controls + cascading + selection/edit logic; unit test. *(Drawer not yet removed — bar built + tested in isolation.)*
2. **Wire into `DashboardDetail`**: top bar + full-width canvas + refined header/edit badge; remove the drawer; update any drawer-structure tests to the bar.
3. **`DashboardCardTile` chrome polish** (glass/elevation/hover-lift + header + chart loading skeleton).
4. **Docs + full gate + prod build + manual-smoke note.**

## Definition of done (golden rules #4/#5)

- New filter-bar tests + all existing dashboard suites green; `tsc`/`lint` clean; full `pnpm test` green first-hand; `pnpm build` succeeds.
- `docs/FRONTEND.md` dashboard section updated (top filter-bar + full-width canvas).
- No change to the gridstack engine, the grounded query/filter logic, tenancy, or `dialog.tsx`.

## Follow-on (not now)

- Focus/"TV" presentation mode; the deferred nested-dialog overflow fix (needs `dialog.tsx`); applying the command-center language elsewhere.
