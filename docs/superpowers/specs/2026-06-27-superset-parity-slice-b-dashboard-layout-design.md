# Superset-parity for charts & dashboards — Slice B: Dashboard layout (free resizable grid)

**Date:** 2026-06-27
**Status:** Design approved; ready for implementation plan
**Depends on:** Slice C (persisted dashboards, tiles, native filters, cross-filter overlay), Slice D (heatmap/sankey tiles) — all complete
**Branch:** active working branch (`feat/novasight-phase-0`), per established practice

---

## Program context

Fifth slice of the Superset-parity program (see
`2026-06-26-superset-parity-slice-a-builder-design.md` for the program overview and
golden-rule constraints). Sequence:

| Slice | Theme | Status |
|-------|-------|--------|
| A | Chart-builder (Explore) parity — query shaping + chart actions | done |
| A2 | Per-type formatting parity — Superset "Customize" panel | done |
| C | Native filters — typed panel, per-tile scoping, cascading, drill | done |
| D | More viz types — heatmap + sankey (full interactivity) | done |
| **B** | **Dashboard layout — free resizable grid** | **this spec** |

The program originally framed B broadly ("resize, rows/columns, tabs, header, fullscreen").
This cycle deliberately scopes it to the **foundational free resizable grid** — drag to
reposition, drag to resize, variable height — per golden rule #4 (ship thin vertical
slices). Tabs, nested row/column containers, per-tile styling, and fullscreen are explicit
follow-ups.

---

## Goal

Turn the dashboard from a **reorder-only** grid into a true **12-column free grid**: in
edit mode tiles drag to reposition (`x`/`y`) and drag-resize (`w`/`h`, variable height); in
view mode the same `x/y/w/h` drive a static placement. This is the layout experience
Superset gives, built on the geometry the data model **already stores**.

- **Edit mode** — pointer drag to move, drag-handles to resize; a keyboard-accessible
  size/position control as the accessibility fallback.
- **View mode** — the same persisted geometry, rendered static (no handles).
- **Every tile kind** — chart and decoration (`text`/`markdown`/`image`/`divider`) all
  participate; chart bodies fill their tile and redraw on resize.
- **Persistence** — through the **existing** `PUT /dashboards/{id}/layout` endpoint; no
  backend schema change.

Nothing about the data path changes: this is a pure display/layout slice. Cross-filter and
drill keep working unchanged. No new configuration and no new tenant/data surface (golden
rules #1 and #3 untouched).

---

## Starting point (verified)

- **Backend is already grid-ready.** `DashboardTile` stores `position, x, y, w, h` as
  integers (12-col convention; `w`/`h` ∈ [1,12], defaults `w=6 h=4`). `PUT
  /dashboards/{id}/layout` (`DashboardLayoutUpdate` → `TileLayout`) already persists
  `{id, position, x, y, w, h}` for every tile, and `TileCreate`/`TileUpdate` accept
  `w`/`h`. **No backend change is required by this slice.**
- **Frontend is the gap.** `DashboardGrid` uses `@dnd-kit/sortable` (`rectSortingStrategy`)
  for reorder only, rendering a uniform `lg:grid-cols-4` Tailwind grid. It applies `w` as
  three discrete column spans via a sm/md/lg dropdown but **ignores `x`, `y`, and `h`**
  (chart bodies are a fixed `h-64`). No free positioning, no drag-resize, no variable
  height.
- **Charts already resize to their container** via a `ResizeObserver` in `ChartRenderer`
  (`instance.resize()` on container change) — so variable tile height works for charts once
  the body fills the tile.
- **React is 19.2.** This drove the engine decision below.

---

## Approach decisions

### Engine: `gridstack` (chosen over `react-grid-layout`)

`react-grid-layout` is the library Superset itself uses, but its `react-draggable`
dependency historically relied on `ReactDOM.findDOMNode`, **removed in React 19**. Rather
than ship a compatibility spike with a fallback, we adopt **`gridstack`** from the start:
it is a framework-agnostic TypeScript core with no React-reconciler/`findDOMNode`
dependency (React-19-safe), supports a 12-column grid with drag + resize + variable height,
and serializes to the same `{x, y, w, h}` shape the model stores. The exact Superset
library is not a requirement — the layout *behavior* and the *data model* are.

Rejected alternatives: custom drag+resize on dnd-kit (reimplements the hard parts —
resize, collision, compaction); CSS-grid + dnd-kit + handle (still hand-rolls
collision/compaction, less polished).

### Integration: React renders the items, gridstack adopts them

`DashboardGrid` renders the `.grid-stack` container and one `.grid-stack-item` per tile
(keyed by `tile.id`, carrying `gs-x/gs-y/gs-w/gs-h/gs-id` from the model). A `useEffect`
calls `GridStack.init(...)` once and **adopts those existing DOM children** as widgets.
**Tile content stays ordinary React** — `DashboardCardTile` with its chart/drill/cross-
filter is unchanged inside the wrapper; gridstack manages only the wrapper geometry. No
portaling, no dependence on gridstack's evolving React-component API. This keeps every
existing tile behavior intact and the gridstack coupling confined to `DashboardGrid`.

### Responsive: one persisted layout + auto-stack

Persist **one** 12-column `x/y/w/h` layout (matching the single geometry the model stores).
On narrow screens gridstack reduces the column count so tiles stack toward a single column;
that derived mobile arrangement is **not persisted** (mobile is view-oriented — we never
write a mobile rearrange back). This avoids a backend model change for per-breakpoint
layouts (an explicit non-goal).

---

## Detailed design (parts)

### Part 1 — gridstack integration behind the `DashboardGrid` boundary

- Add `gridstack` to the frontend dependencies; import its CSS (`gridstack.css`) once.
- Rewrite `DashboardGrid` to render `.grid-stack` + `.grid-stack-item` markup and
  initialize gridstack imperatively in a `useEffect` (ref to the container). Init options:
  `column: 12`, a fixed `cellHeight` (px per row unit — a display constant), `margin`
  (gutter), `float: false` (vertical compaction, RGL-like; no overlapping gaps),
  `handle` bound to the tile's grip element, `disableDrag`/`disableResize` derived from
  `editing`.
- **Lifecycle:** init once on mount; tear down (`grid.destroy(false)`) on unmount;
  toggle drag/resize enablement when `editing` changes (`grid.enableMove`/`enableResize`)
  rather than re-initializing; re-sync widgets when tiles are added/removed (add/remove the
  corresponding widget, or re-render items keyed by id and let gridstack reconcile). The
  whole gridstack surface stays inside this one component.
- **Smoke test (not gesture):** initialize → render N items → destroy without throwing
  under jsdom; assert each tile renders a `.grid-stack-item` with the right `gs-*` attrs.

### Part 2 — tile geometry & rendering (`DashboardCardTile`)

- Remove `useSortable` (dnd-kit) and `spanForW`/`SIZE_TO_W`/`sizeFromW` from the tile —
  gridstack now owns positioning and sizing.
- The tile fills its gridstack item: outer container `h-full`; the chart body becomes
  `h-full` (drop the fixed `h-64`) so `ChartRenderer`'s existing `ResizeObserver` redraws
  on resize. Decoration tiles (text/markdown/image/divider) fill/scroll within the tile.
- Keep the grip handle (now gridstack's drag `handle`) and the remove button in edit mode.
  Replace the sm/md/lg **size dropdown** with drag-resize + the Part 5 control.
- Chart actions menu, drill modals, cross-filter `onSelectPoints`, and the "Filtered"
  badge are unchanged.

### Part 3 — edit/view modes & persistence

- **View mode:** drag/resize disabled; tiles render static at their `x/y/w/h`.
- **Edit mode:** drag/resize enabled from the grip handle; a chart click never starts a
  drag (handle-scoped drag), and cross-filter emission is already disabled while editing.
- **Persistence:** on gridstack's `change` event (edit-mode only, debounced), read
  `grid.save(false)` and map nodes → `{ id, x, y, w, h }`; derive `position` as **row-major
  order** (sort by `y` then `x`) so the server's `order_by position` and any non-grid
  consumer stay coherent. Apply optimistically via `queryClient.setQueryData` then
  `setLayout.mutate({ tiles })` — the same endpoint and optimistic pattern used today,
  sourced from gridstack instead of `arrayMove`.

### Part 4 — responsive behavior

- One persisted 12-col layout. Configure gridstack's responsive column reduction so narrow
  viewports collapse toward a single column (a display-constant breakpoint map). The
  collapsed arrangement is not written back. Desktop is the authoring surface.

### Part 5 — accessibility fallback

- gridstack drag/resize is pointer-oriented and not keyboard-operable, which would regress
  today's keyboard reorder. Provide a per-tile **"Size & position"** control in edit mode
  (e.g. a small popover with keyboard-operable steppers for `w` and `h`, optionally `x`/`y`),
  writing the **same** layout-update path as a drag. Pointer users drag; keyboard users use
  the control. Full keyboard-drag is documented as a known gridstack limitation.

### Part 6 — testing

jsdom cannot simulate drag/resize gestures, so tests assert the **logic seams**, treating
gridstack as a trusted dependency:

- tiles → `.grid-stack-item` `gs-*` attributes (Part 1);
- the `change` → `setLayout` payload mapping, including row-major `position` (Part 3);
- view mode renders without drag/resize affordances; edit mode exposes the grip + size
  control (Parts 2, 3, 5);
- the Part 5 control writes `{ w, h }` (and `x`/`y` if included) through the update path;
- a gridstack init/teardown smoke test (no throw under jsdom).

Existing dashboard tests (cross-filter, native filters, drill) must stay green — this slice
preserves their behavior.

### Part 7 — golden rules & documentation

- **#1 (no hardcoded config):** grid constants (`column`, `cellHeight`, `margin`,
  breakpoints) are frontend **display** constants, not env/tenant config. No new settings.
- **#3 (grounded/read-only):** pure layout/display change; no query, data-path, or
  tenancy change. Cross-filter and drill keep using the governed semantic paths.
- **#4 (thin slice):** the free resizable grid only; tabs/containers/styling/fullscreen
  deferred.
- **#5 (done = tested + typed + documented):** Vitest seams + `tsc`/`lint` green; a new
  **Dashboard layout** section in `docs/DASHBOARDS.md` covering the grid model, edit/view
  modes, the persistence mapping, responsive stacking, and the a11y fallback.

---

## Non-goals (explicit follow-ups)

- Tabs within a dashboard.
- Nested row/column container components.
- Per-tile styling (backgrounds, borders, colours), headers as a distinct component.
- Fullscreen / present mode.
- Per-breakpoint **persisted** layouts (we persist one 12-col layout; mobile auto-stacks).
- Undo/redo of layout edits.

---

## Risks & mitigations

- **gridstack ↔ React rendering coordination.** The "React renders items, gridstack
  adopts" pattern must keep gridstack's view consistent when tiles are added/removed and
  when `editing` toggles. Mitigation: confine all gridstack calls to `DashboardGrid`,
  toggle enablement rather than re-init, and cover add/remove/toggle in the smoke + seam
  tests.
- **Layout thrash / save storms.** Dragging fires many `change` events. Mitigation:
  debounce the persist; apply optimistic cache update first so the grid never snaps back.
- **Variable-height charts.** Relies on `ChartRenderer`'s existing `ResizeObserver`.
  Mitigation: ensure the chart body is `h-full`; smoke-verify a tile resize triggers a
  renderer resize (seam-level: the body fills the tile).
- **Accessibility regression.** Drag is pointer-only. Mitigation: the Part 5 keyboard
  control covers sizing/placement; documented limitation for keyboard-drag.
