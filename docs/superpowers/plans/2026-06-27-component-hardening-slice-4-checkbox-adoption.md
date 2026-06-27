# Component Hardening Slice 4 — Checkbox Adoption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace 33 bare browser-native `<input type="checkbox">` across 9 files (chart-format panels + wizards) with the hardened `<Checkbox>` primitive, for a themed, consistent checkbox everywhere.

**Architecture:** A uniform, behavior-preserving mechanical swap. Each bare checkbox becomes `<Checkbox>` (`@/components/ui/checkbox`), which already carries `accent-primary`, the shared `focusRing`, and `h-4 w-4 rounded border-input`. Every behavioral prop and a11y handle is kept; surrounding `<label>`/`<Label htmlFor>` wrappers stay.

**Tech Stack:** React 19, TypeScript, Vite 8, Tailwind v4, Vitest + Testing Library.

## Global Constraints

- **The swap rule (apply to every bare checkbox):** replace
  `<input type="checkbox" {…props} />` with `<Checkbox {…props} />` — DROP the
  explicit `type="checkbox"` (the primitive sets it), KEEP every other prop
  verbatim (`checked`/`defaultChecked`, `onChange`, `id`, `aria-label`,
  `disabled`, any `value`). The bare checkboxes have NO `className`, so there is
  nothing to merge.
- **Keep wrappers unchanged:** the surrounding `<label className="flex items-center gap-2">…Text</label>`, `<div className="flex items-center gap-2"><Label htmlFor=…/></div>`, and table-cell markup stay exactly as-is.
- **Add the import** `import { Checkbox } from "@/components/ui/checkbox";` to each file that doesn't already have it.
- **Behavior-preserving.** No new props, no label rewiring, no `Field` adoption. Do NOT touch `type="radio"`/`file`/`number` inputs.
- **Adoption marker for tests:** the hardened `<Checkbox>` renders the class `accent-primary` (the bare `<input>` had none). Tests assert `toHaveClass("accent-primary")` on a swapped checkbox, resolved via its preserved handle (`role="checkbox"` + accessible name, via label text or `aria-label`).
- The working tree has **unrelated user WIP** (dialog.tsx, Builder.tsx, backend, `docs/FRONTEND.md`, configs). Each task `git add`s ONLY its files; never `git add -A`/`.`. `docs/FRONTEND.md` is pre-modified → Task 3 is controller-handled.
- Run commands from `d:\Novasight_v2\frontend`. `@/` alias → `frontend/src/`. Commit after each task.

### Concrete before/after examples (the only patterns that occur)

Pattern A — `<label>`-wrapped (chart-format panels, e.g. CartesianControls):
```tsx
// before
<label className="flex items-center gap-2">
  <input
    type="checkbox"
    checked={co.stacked ?? false}
    onChange={(e) => set({ stacked: e.target.checked })}
  />
  Stacked
</label>
// after
<label className="flex items-center gap-2">
  <Checkbox
    checked={co.stacked ?? false}
    onChange={(e) => set({ stacked: e.target.checked })}
  />
  Stacked
</label>
```

Pattern B — `<div>` + `<Label htmlFor>` (SharedFormatControls):
```tsx
// before
<input
  id="sf-legend-show"
  type="checkbox"
  checked={legend.show !== false}
  onChange={(e) => setLegend({ show: e.target.checked })}
/>
// after
<Checkbox
  id="sf-legend-show"
  checked={legend.show !== false}
  onChange={(e) => setLegend({ show: e.target.checked })}
/>
```

Pattern C — table cell with `aria-label` (PipelineWizard):
```tsx
// before
<input
  type="checkbox"
  aria-label={`Include ${f.source_name}`}
  checked={f.included}
  onChange={(e) => patchField(f.source_name, { included: e.target.checked })}
/>
// after
<Checkbox
  aria-label={`Include ${f.source_name}`}
  checked={f.included}
  onChange={(e) => patchField(f.source_name, { included: e.target.checked })}
/>
```

---

### Task 1: Adopt `<Checkbox>` in the chart-format panels

**Files:**
- Modify: `frontend/src/components/chart/format/CartesianControls.tsx` (9 checkboxes)
- Modify: `frontend/src/components/chart/format/GaugeControls.tsx` (6)
- Modify: `frontend/src/components/chart/format/SharedFormatControls.tsx` (6)
- Modify: `frontend/src/components/chart/format/PieControls.tsx` (3)
- Modify: `frontend/src/components/chart/format/FunnelControls.tsx` (2)
- Modify: `frontend/src/components/chart/format/TreemapControls.tsx` (2)
- Test: `frontend/src/test/formatControls.test.tsx` (extend)

**Interfaces:**
- Consumes: `Checkbox` from `@/components/ui/checkbox`.
- Produces: no API change to any panel.

- [ ] **Step 1: Write the failing test**

In `frontend/src/test/formatControls.test.tsx`, append inside the existing `describe("FormatControls type-awareness", …)` block (the file already imports `FormatControls`, `render`, `screen`, `noop`, `base`):

```tsx
  it("renders the cartesian 'Stacked' toggle as the hardened Checkbox", () => {
    render(<FormatControls options={base} setOptions={noop} chartType="bar" />);
    expect(screen.getByRole("checkbox", { name: "Stacked" })).toHaveClass(
      "accent-primary"
    );
  });
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pnpm exec vitest run src/test/formatControls.test.tsx`
Expected: the new test FAILS (the bare `<input type="checkbox">` has no `accent-primary` class).

- [ ] **Step 3: Apply the swap rule to all six files**

In each of the six files above, add `import { Checkbox } from "@/components/ui/checkbox";` (near the other `@/components/ui/*` imports) and apply the swap rule from Global Constraints to EVERY `<input type="checkbox" … />` (Pattern A for the `<label>`-wrapped ones, Pattern B for the `id`+`<Label>` ones in SharedFormatControls). Drop each `type="checkbox"`; keep all other props.

- [ ] **Step 4: Confirm completeness (no bare checkbox left in these files)**

Run: `grep -rn 'type="checkbox"' src/components/chart/format/`
Expected: NO output (every format-panel checkbox is now `<Checkbox>`).

- [ ] **Step 5: Run the test + existing suite to verify green**

Run: `pnpm exec vitest run src/test/formatControls.test.tsx`
Expected: PASS (the new adoption test + the existing type-awareness tests — those query by text, unaffected by the element swap).

- [ ] **Step 6: Type check**

Run: `pnpm exec tsc --noEmit`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/chart/format/CartesianControls.tsx frontend/src/components/chart/format/GaugeControls.tsx frontend/src/components/chart/format/SharedFormatControls.tsx frontend/src/components/chart/format/PieControls.tsx frontend/src/components/chart/format/FunnelControls.tsx frontend/src/components/chart/format/TreemapControls.tsx frontend/src/test/formatControls.test.tsx
git commit -m "refactor(ui): chart-format panels use the hardened Checkbox"
```

---

### Task 2: Adopt `<Checkbox>` in the wizards

**Files:**
- Modify: `frontend/src/components/pipeline/PipelineWizard.tsx` (3 checkboxes)
- Modify: `frontend/src/pages/Pipelines.tsx` (1 — the "Enabled" toggle)
- Modify: `frontend/src/components/schedule/SchedulesPanel.tsx` (1 — the row-select toggle)
- Test: `frontend/src/test/pipelines.test.tsx` (extend)

**Interfaces:**
- Consumes: `Checkbox` from `@/components/ui/checkbox`.
- Produces: no API change.

- [ ] **Step 1: Add the failing adoption assertion**

In `frontend/src/test/pipelines.test.tsx`, in the existing test
`it("designs a SQL pipeline with a field map and merge-by-primary-key", …)`,
add ONE assertion immediately after the existing line
`await screen.findByLabelText("Include id");` (around line 285):

```tsx
    expect(screen.getByLabelText("Include id")).toHaveClass("accent-primary");
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pnpm exec vitest run src/test/pipelines.test.tsx`
Expected: that test FAILS at the new assertion (the bare PipelineWizard checkbox lacks `accent-primary`).

- [ ] **Step 3: Apply the swap rule to the three files**

In each file, add `import { Checkbox } from "@/components/ui/checkbox";` and apply the swap rule:
- `PipelineWizard.tsx`: the 3 table-cell checkboxes (Pattern C — `Include …`, `Primary key …`, `Partition by …`), keep each `aria-label`.
- `Pipelines.tsx`: the "Enabled" checkbox (keep its `aria-label="Enabled"` / `checked` / `onChange`).
- `SchedulesPanel.tsx`: the row-select checkbox (keep its `checked`/`onChange`/`aria-label`).

- [ ] **Step 4: Confirm completeness**

Run: `grep -rn 'type="checkbox"' src/components/pipeline/PipelineWizard.tsx src/pages/Pipelines.tsx src/components/schedule/SchedulesPanel.tsx`
Expected: NO output.

- [ ] **Step 5: Run the regression suites + type check**

Run: `pnpm exec vitest run src/test/pipelines.test.tsx src/test/operations.test.tsx`
Expected: PASS (pipelines drives the wizard checkboxes by `aria-label`, preserved; operations renders the schedules view).

Run: `pnpm exec tsc --noEmit`
Expected: PASS.

> The `Pipelines.tsx` "Enabled" and `SchedulesPanel.tsx` row-select checkboxes have no dedicated adoption assertion (not isolated in a test); they are verified by `tsc`, the completeness grep, and the regression suites staying green — identical pattern to the asserted PipelineWizard checkbox.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/pipeline/PipelineWizard.tsx frontend/src/pages/Pipelines.tsx frontend/src/components/schedule/SchedulesPanel.tsx frontend/src/test/pipelines.test.tsx
git commit -m "refactor(ui): pipeline/schedule wizards use the hardened Checkbox"
```

---

### Task 3: Docs + full-gate verification (controller-executed)

**Files:**
- Modify: `docs/FRONTEND.md`

> **Controller note:** `docs/FRONTEND.md` is in the user's uncommitted WIP. Executed by the controller: stash the WIP for that file, append the docs, commit only the docs change, then `git stash pop` — same approach as slices 1–3.

- [ ] **Step 1: Update the docs**

In `docs/FRONTEND.md`, under the `### Control contract (core primitives)` subsection, append a bullet:

```markdown
- **Checkboxes:** the chart-format panels and the pipeline/schedule wizards use
  the hardened `Checkbox` (themed `accent-primary` + shared ring) — no more bare
  browser-native checkboxes (slice 4).
```

- [ ] **Step 2: Run the FULL gate first-hand**

Run: `pnpm exec tsc --noEmit`
Expected: PASS (0 errors).

Run: `pnpm lint`
Expected: PASS (0 errors; warning count unchanged from the 44 baseline).

Run: `pnpm test`
Expected: PASS — all suites green, including the extended `formatControls` and `pipelines` tests.

> If a pre-existing test asserted a bare-checkbox detail, update it to the primitive's behavior — do not weaken it.

- [ ] **Step 3: Commit**

```bash
git add docs/FRONTEND.md
git commit -m "docs(frontend): checkboxes now use the hardened Checkbox primitive"
```

---

## Self-Review

**Spec coverage:**
- 28 chart-format-panel checkboxes (6 files) → Task 1 (with completeness grep). ✓
- 5 wizard checkboxes (3 files) → Task 2 (with completeness grep). ✓
- Docs + full gate (first-hand) → Task 3. ✓
- Out of scope (radio/file/number, label rewiring) → untouched. ✓

**Placeholder scan:** The swap is a uniform mechanical transformation specified by an exact rule + three concrete before/after examples (the only patterns present) + a completeness grep per task. Enumerating all 33 identical swaps would add noise, not clarity; the rule + examples + grep fully determine the work. No TBD/TODO. The two un-asserted wizard checkboxes are called out with rationale + alternative verification (grep + regression), not a vague gap. ✓

**Type consistency:**
- `Checkbox` imported from `@/components/ui/checkbox` everywhere. ✓
- Adoption marker `accent-primary` matches the hardened `Checkbox` base class. ✓
- Asserted handles preserved: cartesian "Stacked" label text (Task 1); "Include id" `aria-label` (Task 2). ✓

No gaps found.
