# Design — Chart Builder Redesign: Three-Pane Pro Builder

- **Date:** 2026-06-27
- **Status:** Approved (design direction + layout); pending spec review + implementation plan
- **Area:** `frontend/` — the `/build` Chart Builder page + the `SemanticQueryBuilder` shelves component
- **Predecessors:** Slices 1–5 hardened the primitives, tokens, and consistency this redesign builds on.
- **Golden rules in play:** #4 (thin slices — prove the risky seam first), #5 (tested + typed + documented), #3 (AI-generated SQL grounded — unchanged; we only rearrange the AI panel).

## ⚠️ Execution prerequisite (blocker)

`frontend/src/pages/Builder.tsx` and `frontend/src/test/builderSemantic.test.tsx` are in the
user's **uncommitted WIP** (the Configure tab-split). This redesign rewrites both. **No code
in this slice may be written until the user commits that WIP**, giving a clean base. The spec
and plan (docs) can be written now; implementation is gated on the commit.

## Summary

Redesign `/build` from today's two-column layout (a 360px "Configure" card + a right column
stacking preview/AI/saved) into a **three-pane pro-BI builder** (the user-approved Layout B):

- **Left — Fields:** model picker + draggable Dimensions/Measures palette.
- **Center — Workspace:** a horizontal **shelf-pills bar** (X · Breakdown · Metrics · Filters)
  above a **dominant chart preview** (the hero), with a slim **Ask in plain English** AI bar beneath.
- **Right — Chart:** chart-type picker + Formatting + Query options (rows/sort/date).
- **Saved charts** move to a top-right drawer; panes stack on narrow screens.

The aim is **restructure + polish reusing all existing logic** — but Layout B specifically
requires one genuine refactor: the `SemanticQueryBuilder` currently wraps the Fields palette
**and** the shelves in a single `<DndContext>`, so splitting them across panes means lifting the
DnD context to the shell and exposing the palette and shelves as separately-placeable parts.

## Problem (current state)

`Builder.tsx` renders `grid-cols-[360px_1fr]`: a sticky "Configure" card (tabs: Query & Model /
Formatting) on the left, and a right column stacking the Preview card + `NLChartPanel` + `SavedChartsList`.
Weaknesses: the **preview isn't the hero** (one card among several), the **shelves are cramped** in a
360px tab, there's **no dominant workspace**, and the hierarchy is flat.

`SemanticQueryBuilder.tsx` is one `<DndContext>` (lines ~250–424) enclosing: the model `Select`,
the draggable Data palette (`PaletteChip`s), the shelves (`Shelf` droppables: X / Breakdown / Metrics /
Filters), granularity, and the chart-type `Select`. All currently stacked vertically.

## Decisions (locked during brainstorming)

| Decision | Choice |
|----------|--------|
| Screen | Chart Builder (`/build`) |
| Aim | Pro layout restructure + polish, reusing existing logic + tests |
| Layout | **B — three-pane** (Fields rail · shelf-pills+preview+AI center · type/format/query rail), confirmed via the visual companion |
| DnD approach | **Lift `<DndContext>` to the shell**; split `SemanticQueryBuilder` into placeable parts (`FieldsPalette`, `Shelves`) so palette (left) and shelves (center) share one context across panes |
| State | `useSemanticBuilder` hook unchanged — all state stays there; parts receive `s` |
| Chart-type picker | Keep the existing `Select` (moved to the right rail). A visual type **gallery** is an interaction upgrade → out of scope |
| Saved charts | Top-right **drawer** toggle (was a list under the chart) |
| Reused unchanged | `useSemanticBuilder`, `ChartRenderer`, `FormatControls`, `QueryControls`, `NLChartPanel`, `SaveChartButton`, `AddToDashboard`, `ChartActionsMenu`, `SavedChartsList`, and `SemanticQueryBuilder`'s internals (`PaletteChip`/`PlacedChip`/`Shelf`/`FilterRow`) |

## Architecture

- **`SemanticQueryBuilder` → split into placeable parts under a lifted DnD context.** Introduce a
  shell/provider that owns the `<DndContext>` + drag-label state + `handleDragStart`/`handleDragEnd`,
  and export two sub-views that render inside it: `FieldsPalette` (model + Dimensions/Measures
  draggable chips) and `Shelves` (the X / Breakdown / Metrics / Filters droppables + granularity).
  The chart-type `Select` becomes a small exported control placed in the right rail. The DnD
  helpers (`filtersAfterDrop`, `SHELF_ACCEPTS`, accept rules) and the `Shelf`/chip internals are
  preserved verbatim — only the **composition** changes (context lifted, palette vs shelves
  separated). The shared context wraps the whole three-pane grid so cross-pane drag works.
- **`Builder.tsx` → three-pane shell.** Renders the lifted `<DndContext>` around a responsive grid:
  left `FieldsPalette`, center (`Shelves` pills bar + `SemanticPreview`/`ChartRenderer` hero +
  `NLChartPanel` bar), right (chart-type + `FormatControls` + `QueryControls`). `SavedChartsList`
  becomes a toggled drawer. The page-level toolbar (`ChartActionsMenu`, `SaveChartButton`,
  `AddToDashboard`) sits on the preview header.
- **Responsive:** three panes on `lg+`; stacked (Fields → workspace → chart options) below.
- **Tokens/polish:** reuse the hardened primitives + `--elevation-*` for pane surfaces; the
  shelf-pills bar and hero preview get deliberate spacing, elevation, and the existing
  `animate-in-up` motion; empty/loading/error states reuse `EmptyState`/`Spinner`/`Alert`.

## Testing strategy

- **Behavior-preserving refactor first.** The DnD restructure (lifting the context, splitting
  palette/shelves) must keep the existing builder suites green: `semanticQueryBuilder.test.tsx`,
  `builderSemantic.test.tsx`, `builderLoadSpec.test.tsx`, `cascadingFilters.test.tsx`. They drive
  the builder by role/label/text (model select, shelf labels, palette chips, filter rows), so the
  refactor must preserve those handles. Any test that asserts the old single-container structure is
  updated to the new structure — not weakened. This suite is the gate that the refactor didn't
  break DnD.
- **Shell structure tests** where unit-testable: the three panes render; the saved-charts drawer
  toggles open/closed; the preview toolbar (save/add/actions) appears when ready.
- **Not jsdom-testable:** the three-pane visual layout + responsive stacking + drag *visuals* —
  verified by the production build + a **manual browser smoke** (drag a field to a shelf across
  panes; resize to mobile; open the saved drawer; run the AI bar). Recorded as a user step.

## Scope decomposition (tasks, ordered to de-risk)

1. **Refactor `SemanticQueryBuilder`:** lift `<DndContext>` to a shell/provider, export
   `FieldsPalette` + `Shelves` (+ a `ChartTypeSelect`), behavior-preserving — `Builder.tsx`
   composes them in a still-working arrangement so all existing builder tests pass. *(the risky seam)*
2. **Rebuild `Builder.tsx`** into the three-pane shell (Fields | shelves-pills+preview+AI | type/format/query),
   inside the lifted context.
3. **Saved-charts drawer** + responsive stacking + AI-bar placement.
4. **Polish:** elevation/spacing, shelf-pills + hero styling, micro-motion, empty/loading/error
   states, a11y (focus order across panes; dnd-kit keyboard).
5. **Docs + full gate + prod build + manual-smoke note.**

## Out of scope

- Visual chart-type **gallery** (keep the `Select`); new query/AI capabilities; other screens;
  `dialog.tsx`; any change to `useSemanticBuilder`'s query/spec logic or the grounding path.

## Definition of done (golden rules #4/#5)

- Existing builder suites green after the refactor (proof DnD preserved); new shell tests added;
  `tsc` + `lint` clean (no new warnings); full `pnpm test` green first-hand; `pnpm build` succeeds.
- `docs/FRONTEND.md` `/build` description updated to the three-pane layout; manual-smoke step recorded.
- No change to the grounded AI/query contract; behavior preserved except the deliberate layout change.

## Follow-on (not now)

- Visual chart-type gallery + more tactile field drag (the "interaction upgrades" tier).
- `dialog.tsx` hardening (still blocked on user WIP).
- Applying the three-pane language to other heavy screens if it lands well.
