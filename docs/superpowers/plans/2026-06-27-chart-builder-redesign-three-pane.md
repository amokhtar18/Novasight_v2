# Chart Builder Redesign (Three-Pane) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign `/build` into a three-pane pro-BI builder (Fields rail · shelf-pills + hero preview + AI · type/format/query rail), reusing all existing logic, by lifting `SemanticQueryBuilder`'s `DndContext` to the page shell and splitting its palette from its shelves.

**Architecture:** Reorganize `SemanticQueryBuilder.tsx` from one monolithic vertical component into composable exports — `BuilderDnd` (the lifted `DndContext` + drag state + handlers), `FieldsPalette`, `Shelves`, `ChartTypeSelect` — keeping every helper, chip, shelf, and the `useSemanticBuilder` hook unchanged. Then rebuild `Builder.tsx` to place those parts in three panes inside one shared `BuilderDnd`. Refactor first (behavior-preserving, tests green), rearrange second.

**Tech Stack:** React 19, TypeScript, Vite 8, Tailwind v4, @dnd-kit/core, Vitest + Testing Library.

## Global Constraints

- **EXECUTION PREREQUISITE:** `frontend/src/pages/Builder.tsx` and `frontend/src/test/builderSemantic.test.tsx` are in the user's uncommitted WIP (the Configure tab-split). **Do not start Task 1 until the user has committed that WIP** (clean base). The controller verifies `git status --porcelain frontend/src/pages/Builder.tsx frontend/src/test/builderSemantic.test.tsx` is EMPTY before dispatching Task 1.
- **Reuse, don't rewrite logic:** `useSemanticBuilder` (the hook in `Builder.tsx`), `ChartRenderer`, `FormatControls`, `QueryControls`, `NLChartPanel`, `SaveChartButton`, `AddToDashboard`, `ChartActionsMenu`, `SavedChartsList`, and the shelf/chip/filter internals + helpers (`filtersAfterDrop`, `parseFilterValues`, `SHELF_ACCEPTS`, `Shelf`, `PaletteChip`, `PlacedChip`, `FilterRow`, `fieldTitle`) are preserved. Only **composition** changes.
- **Keep helper exports stable:** `filtersAfterDrop` and `parseFilterValues` must stay exported from `@/components/chart/SemanticQueryBuilder` (semanticQueryBuilder.test.tsx imports them there).
- **De-risk ordering:** Task 1 is a behavior-preserving extraction — the existing builder suites are its gate. Layout changes start in Task 2.
- **Tests updated, never weakened:** the three-pane layout removes the Configure tabs (Formatting moves to an always-visible right rail), so the WIP tab test in `builderSemantic.test.tsx` (the `it("splits configuration into Query & Model and Formatting tabs", …)`) is **rewritten** to assert the new layout (format controls always present; no tab), not deleted.
- **Hardened primitives only:** use the existing `ui/` primitives + `--elevation-*`/`--z-*` tokens; no new tokens.
- **Layout/DnD are not jsdom-testable:** unit tests cover structure (panes render, parts present, drawer toggles, query wiring) and the preserved DnD logic; the three-pane visual + responsive + drag *visuals* are verified by `pnpm build` + a **manual browser smoke** (recorded for the user).
- The working tree has unrelated user WIP (dialog.tsx, backend, configs, `docs/FRONTEND.md`). Each task `git add`s ONLY its files; never `git add -A`/`.`. `docs/FRONTEND.md` (Task 5) is controller-handled via stash.
- Run commands from `d:\Novasight_v2\frontend`. `@/` alias → `frontend/src/`. Commit after each task.

## File structure

- Modify `frontend/src/components/chart/SemanticQueryBuilder.tsx` — reorganize into exports: `BuilderDnd`, `FieldsPalette`, `Shelves`, `ChartTypeSelect` (Task 1). Helpers/primitives/constants stay in this file.
- Modify `frontend/src/pages/Builder.tsx` — three-pane shell composing the parts (Tasks 2–4).
- Create `frontend/src/components/chart/builder/SavedChartsDrawer.tsx` — a toggled drawer wrapping `SavedChartsList` (Task 3).
- Modify `frontend/src/test/builderSemantic.test.tsx` — rewrite the tab test for the new layout (Task 2).
- Add/extend tests: `frontend/src/test/builderShell.test.tsx` (new — three-pane structure + drawer) (Task 3).
- Modify `docs/FRONTEND.md` (Task 5, controller).

---

### Task 1: Extract `BuilderDnd` / `FieldsPalette` / `Shelves` / `ChartTypeSelect` (behavior-preserving)

**Files:**
- Modify: `frontend/src/components/chart/SemanticQueryBuilder.tsx`
- Test: existing builder suites are the gate (no new test file).

**Interfaces (Produces — later tasks rely on these exact signatures):**
- `export function BuilderDnd({ s, children }: { s: SemanticBuilder; children: React.ReactNode }): JSX.Element` — renders `<DndContext …>{children}<DragOverlay>…</DragOverlay></DndContext>`; owns the drag-label state + `handleDragStart`/`handleDragEnd` (moved verbatim from the old component). Must wrap any subtree containing `FieldsPalette` and `Shelves`.
- `export function FieldsPalette({ s }: { s: SemanticBuilder }): JSX.Element` — the model `Select` (keeps `id="b-model"`, `<Label htmlFor="b-model">Model</Label>`) + the draggable Dimensions/Measures palette (the `PaletteChip` lists, verbatim).
- `export function Shelves({ s }: { s: SemanticBuilder }): JSX.Element` — the X / Breakdown / Metrics / Filters `Shelf` droppables + the granularity `Select` (keeps `id="b-sem-gran"`, `<Label>Granularity</Label>`) + the breakdown/first-metric hint, verbatim.
- `export function ChartTypeSelect({ s }: { s: SemanticBuilder }): JSX.Element` — the chart-type `Select` (keeps `id="b-sem-type"`, `<Label htmlFor="b-sem-type">Chart type</Label>`) + the heatmap/sankey hint, verbatim.
- `filtersAfterDrop`, `parseFilterValues` remain exported unchanged. The `models-empty` guard (the "No semantic models" message) moves into `FieldsPalette`.
- Keep a thin `export function SemanticQueryBuilder({ s }: { s: SemanticBuilder })` that renders `<BuilderDnd s={s}><div className="space-y-4"><FieldsPalette s={s}/><Shelves s={s}/><ChartTypeSelect s={s}/></div></BuilderDnd>` — so `Builder.tsx` (unchanged this task) still works and every existing test passes. (This compat component is removed in Task 2.)

- [ ] **Step 1: Reorganize the component**

In `frontend/src/components/chart/SemanticQueryBuilder.tsx`, split the single `SemanticQueryBuilder` component (current lines ~209–426) into the four exported parts above. Mechanically: move the `<DndContext sensors… onDragStart onDragEnd>` wrapper + `dragLabel` state + `sensors` + `handleDragStart`/`handleDragEnd` + `<DragOverlay>` into `BuilderDnd`; move the model `Select` + Data palette block into `FieldsPalette`; move the four `<Shelf>`s + granularity + breakdown hint into `Shelves`; move the chart-type `Select` + heatmap/sankey hint into `ChartTypeSelect`. Keep `PaletteChip`, `PlacedChip`, `Shelf`, `FilterRow`, `fieldTitle`, `CHART_TYPES`, `GRANULARITIES`, `SHELF_ACCEPTS`, `FILTER_OPERATORS`, `VALUELESS_OPERATORS`, `filtersAfterDrop`, `parseFilterValues` exactly as they are. `FieldsPalette` keeps the `modelsLoading`/empty guards (returns the "No semantic models" message or null). Add the thin compat `SemanticQueryBuilder` shown in Interfaces.

  - `BuilderDnd` reads the dims/measures for the drag label from `s.model` (same as today: `fieldTitle(data.kind === "measure" ? s.model?.measures ?? [] : s.model?.dimensions ?? [], data.field)`).

- [ ] **Step 2: Run the builder suites to verify they still pass (the gate)**

Run: `pnpm exec vitest run src/test/semanticQueryBuilder.test.tsx src/test/builderSemantic.test.tsx src/test/builderLoadSpec.test.tsx src/test/cascadingFilters.test.tsx`
Expected: ALL PASS unchanged — the compat `SemanticQueryBuilder` renders the same DOM (model select, shelves labels, palette field titles, granularity, filters), so every handle the tests query is preserved. If any fail, the extraction changed observable structure — fix the extraction, do not edit the tests in this task.

- [ ] **Step 3: Type check + lint**

Run: `pnpm exec tsc --noEmit && pnpm lint`
Expected: PASS (0 errors; warnings unchanged).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/chart/SemanticQueryBuilder.tsx
git commit -m "refactor(builder): split SemanticQueryBuilder into BuilderDnd/FieldsPalette/Shelves/ChartTypeSelect"
```

---

### Task 2: Three-pane `Builder.tsx` shell

**Files:**
- Modify: `frontend/src/pages/Builder.tsx`
- Modify: `frontend/src/test/builderSemantic.test.tsx` (rewrite the tab test)

**Interfaces:**
- Consumes: `BuilderDnd`, `FieldsPalette`, `Shelves`, `ChartTypeSelect` from `@/components/chart/SemanticQueryBuilder`; `useSemanticBuilder`, `buildChartQuery`, `SemanticBuilder`, `SemanticPreview` (kept in `Builder.tsx`), `ChartRenderer`, `FormatControls`, `QueryControls`, `NLChartPanel`, `SaveChartButton`, `AddToDashboard`, `ChartActionsMenu`.
- Produces: the redesigned page. `useSemanticBuilder` and `buildChartQuery` exports unchanged (other modules import `SemanticBuilder`/`buildChartQuery` from `@/pages/Builder`).

- [ ] **Step 1: Rewrite the tab test for the new layout (write the failing test first)**

In `frontend/src/test/builderSemantic.test.tsx`, REPLACE the `it("splits configuration into Query & Model and Formatting tabs", …)` test with one asserting the new always-visible layout (no tabs):

```tsx
  it("shows the shelves and the formatting controls together (no config tabs)", () => {
    renderBuilder();
    // Shelves (left/center) and the formatting controls (right rail) are BOTH
    // visible at once — the Configure tab-split is gone.
    expect(screen.getByLabelText(/^model$/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/chart title/i)).toBeInTheDocument();
    // There is no Query & Model / Formatting tablist anymore.
    expect(screen.queryByRole("tab", { name: /formatting/i })).not.toBeInTheDocument();
  });
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pnpm exec vitest run src/test/builderSemantic.test.tsx`
Expected: the new test FAILS (current Builder still has the tabs; chart title is hidden behind the Formatting tab).

- [ ] **Step 3: Rewrite `Builder.tsx` into the three-pane shell**

Replace the `Builder()` component body (keep `useSemanticBuilder`, `buildChartQuery`, `BuilderQueryState`, `DEFAULT_LIMIT`, `NO_X_TYPES`, and `SemanticPreview` in the file). New layout — wrap everything in one `BuilderDnd`, drop the old `Configure` card + `Tabs`, drop the compat `SemanticQueryBuilder`/`SavedChartsList`-under-preview:

```tsx
export function Builder() {
  const semantic = useSemanticBuilder();
  const [aiResult, setAiResult] = useState<NLChartResponse | null>(null);

  return (
    <div className="animate-in-up">
      <PageHeader
        title="Chart builder"
        description="Drag governed fields onto the shelves to build a chart — or describe one in plain English — then format and save it."
      />

      <BuilderDnd s={semantic}>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[220px_1fr_220px]">
          {/* LEFT — Fields */}
          <Card className="bg-card/70 lg:sticky lg:top-20 lg:self-start" elevation="sm">
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-sm">
                <Layers className="h-4 w-4" aria-hidden /> Fields
              </CardTitle>
            </CardHeader>
            <CardContent>
              <FieldsPalette s={semantic} />
            </CardContent>
          </Card>

          {/* CENTER — shelves + preview + AI */}
          <div className="space-y-4">
            <Card className="bg-card/70" elevation="sm">
              <CardContent className="pt-6">
                <Shelves s={semantic} />
              </CardContent>
            </Card>
            <SemanticPreview s={semantic} />
            <NLChartPanel onResult={setAiResult} />
            {aiResult && (
              <div className="flex flex-wrap justify-end gap-2">
                <SaveChartButton spec={aiResult.spec} defaultName={aiResult.spec.options?.title ?? "AI chart"} sourceKind="semantic" />
                <AddToDashboard spec={aiResult.spec} title={aiResult.spec.options?.title ?? "AI chart"} data={aiResult.data} />
              </div>
            )}
          </div>

          {/* RIGHT — type + format + query */}
          <Card className="bg-card/70 lg:sticky lg:top-20 lg:self-start" elevation="sm">
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-sm">
                <SlidersHorizontal className="h-4 w-4" aria-hidden /> Chart
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <ChartTypeSelect s={semantic} />
              <FormatControls options={semantic.options} setOptions={semantic.setOptions} chartType={semantic.chartType} />
              <QueryControls s={semantic} />
            </CardContent>
          </Card>
        </div>
      </BuilderDnd>
    </div>
  );
}
```

Update the imports at the top of `Builder.tsx`: replace `import { SemanticQueryBuilder } from "@/components/chart/SemanticQueryBuilder";` with `import { BuilderDnd, FieldsPalette, Shelves, ChartTypeSelect } from "@/components/chart/SemanticQueryBuilder";`, remove the `Tabs`/`TabsContent`/`TabsList`/`TabsTrigger` and `CardDescription` imports if now unused, and remove the `SavedChartsList` import (it moves to the drawer in Task 3 — temporarily drop it; Task 3 re-adds it via the drawer). Keep `Layers`, `SlidersHorizontal` from lucide.

- [ ] **Step 4: Run the builder suites**

Run: `pnpm exec vitest run src/test/builderSemantic.test.tsx src/test/builderLoadSpec.test.tsx src/test/cascadingFilters.test.tsx`
Expected: PASS — the rewritten tab test passes; the others still pass (model select, shelves, palette titles, granularity, chart-renderer, save button all present in the new layout). `FormatControls` is now always mounted, so `getByLabelText(/chart title/i)` resolves.

- [ ] **Step 5: Type check + lint**

Run: `pnpm exec tsc --noEmit && pnpm lint`
Expected: PASS.

- [ ] **Step 6: Manual smoke (record output)**

Run: `pnpm dev`, open `/build`. Confirm: three panes render; dragging a field from the left **Fields** pane onto a center **shelf** works (cross-pane DnD); the preview updates; the right rail shows type + formatting + query. (jsdom can't verify this — it's the real proof Task-1's DnD lift works across panes.)

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/Builder.tsx frontend/src/test/builderSemantic.test.tsx
git commit -m "feat(builder): three-pane layout (fields rail · shelves+preview · chart rail)"
```

---

### Task 3: Saved-charts drawer + responsive stacking

**Files:**
- Create: `frontend/src/components/chart/builder/SavedChartsDrawer.tsx`
- Modify: `frontend/src/pages/Builder.tsx`
- Test: `frontend/src/test/builderShell.test.tsx`

**Interfaces:**
- Consumes: `SavedChartsList` (`{ onEdit }`), `Dialog` primitive, `Button`.
- Produces: `export function SavedChartsDrawer({ onEdit }: { onEdit: (spec: ChartSpec) => void })` — a "Saved charts" toggle button that opens the existing `SavedChartsList` in a `Dialog` (reusing the hardened modal), so it no longer competes with the preview.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/test/builderShell.test.tsx` (mock hooks like `builderSemantic.test.tsx` does — copy its `vi.mock` block + `beforeEach`), asserting the drawer is closed initially and opens on click:

```tsx
  it("opens the saved-charts drawer from the toolbar", () => {
    renderBuilder();
    expect(screen.queryByRole("heading", { name: /saved charts/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /saved charts/i }));
    expect(screen.getByRole("heading", { name: /saved charts/i })).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pnpm exec vitest run src/test/builderShell.test.tsx`
Expected: FAIL (no "Saved charts" toggle yet).

- [ ] **Step 3: Create the drawer + wire it into the page header**

Create `frontend/src/components/chart/builder/SavedChartsDrawer.tsx`:

```tsx
import { useState } from "react";
import { BookMarked } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { SavedChartsList } from "@/components/chart/SavedChartsList";
import type { ChartSpec } from "@/types/api";

export function SavedChartsDrawer({ onEdit }: { onEdit: (spec: ChartSpec) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        <BookMarked className="h-4 w-4" aria-hidden /> Saved charts
      </Button>
      <Dialog open={open} onOpenChange={setOpen} title="Saved charts">
        <SavedChartsList onEdit={(spec) => { onEdit(spec); setOpen(false); }} />
      </Dialog>
    </>
  );
}
```

In `Builder.tsx`, render the drawer in the `PageHeader` area (PageHeader supports an actions slot via its children/sibling; place the toggle in a flex row beside the title) and pass `onEdit={semantic.loadSpec}`. Import `SavedChartsDrawer`.

- [ ] **Step 4: Responsive verification (read-through)**

Confirm the grid uses `grid-cols-1 lg:grid-cols-[220px_1fr_220px]` so panes stack below `lg`. No code change if already set in Task 2.

- [ ] **Step 5: Run tests + type check**

Run: `pnpm exec vitest run src/test/builderShell.test.tsx src/test/builderSemantic.test.tsx`
Expected: PASS.

Run: `pnpm exec tsc --noEmit && pnpm lint`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/chart/builder/SavedChartsDrawer.tsx frontend/src/pages/Builder.tsx frontend/src/test/builderShell.test.tsx
git commit -m "feat(builder): saved-charts drawer + responsive three-pane stacking"
```

---

### Task 4: Polish — shelf-pills styling, hero preview, elevation, a11y

**Files:**
- Modify: `frontend/src/components/chart/SemanticQueryBuilder.tsx` (the `Shelves` layout only)
- Modify: `frontend/src/pages/Builder.tsx` (`SemanticPreview` sizing + AI bar spacing)

**Interfaces:** none new — styling only.

- [ ] **Step 1: Make `Shelves` a horizontal pills bar**

In `Shelves`, change the vertical `space-y-*` stack to a responsive flex/grid so X · Breakdown · Metrics · Filters sit as a compact bar across the canvas top: wrap the four `<Shelf>`s in `<div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">` (X and Filters can be narrower; Breakdown/Metrics wider). Keep each `<Shelf>`'s internals + labels unchanged (tests query the labels). Granularity sits inline under the X shelf when `s.isTimeX`.

- [ ] **Step 2: Make the preview the hero**

In `SemanticPreview`, raise the chart height (`className="h-[420px]"` on `ChartRenderer`, up from `h-80`) and give the card `elevation="md"`. Keep the empty/loading/error states.

- [ ] **Step 3: a11y pass**

Verify (and fix if needed): logical DOM order is Fields → Shelves → Preview → AI → right rail (so keyboard tab order is sensible across panes); the drawer toggle and preview toolbar buttons are reachable; the dnd-kit `PointerSensor` is unchanged (keyboard DnD is a documented follow-on, not added here). No assertion change.

- [ ] **Step 4: Run the full builder suites + gate**

Run: `pnpm exec vitest run src/test/builderSemantic.test.tsx src/test/builderShell.test.tsx src/test/cascadingFilters.test.tsx src/test/builderLoadSpec.test.tsx`
Expected: PASS (styling-only; labels/handles unchanged).

Run: `pnpm exec tsc --noEmit && pnpm lint`
Expected: PASS.

- [ ] **Step 5: Manual smoke (record output)**

`pnpm dev` → `/build`: shelves read as a clean pills bar; the preview dominates; panes stack on a narrow window; the saved drawer opens; AI bar generates.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/chart/SemanticQueryBuilder.tsx frontend/src/pages/Builder.tsx
git commit -m "style(builder): horizontal shelf-pills bar + hero preview + elevation"
```

---

### Task 5: Docs + full gate + prod build (controller-executed)

**Files:**
- Modify: `docs/FRONTEND.md`

> **Controller note:** `docs/FRONTEND.md` is in the user's WIP. Controller stashes it, edits, commits, pops — as in slices 1–5.

- [ ] **Step 1: Update the `/build` description**

In `docs/FRONTEND.md`, update the `/build` row of the route table (and the design-system section if it references the Configure tabs) to describe the three-pane layout: "Fields rail (draggable governed dims/measures) · center shelf-pills (X/Breakdown/Metrics/Filters) + hero preview + NL→chart bar · right rail (chart type + formatting + query options); saved charts in a drawer." Remove the now-stale "Configure panel split into a Query & Model tab and a Formatting tab" wording.

- [ ] **Step 2: Run the FULL gate first-hand**

Run: `pnpm exec tsc --noEmit` → PASS.
Run: `pnpm lint` → PASS (0 errors; warnings unchanged from 44 baseline).
Run: `pnpm test` → PASS — all suites, including the rewritten builder tests + `builderShell`.
Run: `pnpm build` → succeeds.

- [ ] **Step 3: Commit**

```bash
git add docs/FRONTEND.md
git commit -m "docs(frontend): Chart Builder three-pane layout"
```

- [ ] **Step 4: Record the manual smoke for the user**

Tell the user to do the browser smoke: cross-pane drag (field → shelf), preview updates, responsive stacking, saved drawer, AI bar — the layout/DnD visuals jsdom can't verify.

---

## Self-Review

**Spec coverage:**
- DnD lift + split into placeable parts → Task 1. ✓
- Three-pane `Builder.tsx` shell → Task 2. ✓
- Saved-charts drawer + responsive → Task 3. ✓
- Polish (pills bar, hero, elevation, a11y) → Task 4. ✓
- Docs + full gate + build + manual smoke → Task 5. ✓
- Behavior-preserving-first ordering (Task 1 gate = existing suites) → enforced in Task 1. ✓
- Tab test rewritten not deleted → Task 2 Step 1. ✓
- Reuse list (hook, renderer, format/query/AI/saved, chips/shelves/helpers) → honored across tasks. ✓
- Out of scope (type gallery, new query/AI, dialog.tsx) → untouched. ✓
- Execution prerequisite (WIP commit) → Global Constraints + controller gate. ✓

**Placeholder scan:** No TBD/TODO. Task 1 specifies the exact exported signatures + a mechanical extraction; Tasks 2–4 give the concrete JSX/structure; layout-only aspects are explicitly verified by manual smoke (stated, not hand-waved). Where the visual JSX will be refined during the manual smoke, that is called out as the verification, not left vague.

**Type consistency:**
- `BuilderDnd`/`FieldsPalette`/`Shelves`/`ChartTypeSelect` all take `{ s: SemanticBuilder }` (BuilderDnd also `children`), imported from `@/components/chart/SemanticQueryBuilder` in Task 2. ✓
- `SavedChartsDrawer({ onEdit })` matches `SavedChartsList`'s `onEdit: (spec: ChartSpec) => void` and `semantic.loadSpec`. ✓
- `useSemanticBuilder`/`buildChartQuery`/`SemanticBuilder` stay exported from `@/pages/Builder` (consumed by `QueryControls`, `SemanticQueryBuilder`). ✓
- Preserved test handles: model `id="b-model"`/label "Model"; granularity `id="b-sem-gran"`/label "Granularity"; type `id="b-sem-type"`; shelf labels "X-axis"/"Breakdown (series)"/"Metrics"/"Filters"; chart-renderer testid; "Save chart" button. ✓

No gaps found.
