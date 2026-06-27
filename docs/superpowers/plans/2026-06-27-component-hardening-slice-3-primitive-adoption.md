# Component Hardening Slice 3 — Primitive Adoption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace 4 hand-rolled full-size text controls in pages with the hardened `<Input>`/`<Textarea>` primitives, so they inherit the shared focus ring + token shadow and the duplicated inline styling is deleted.

**Architecture:** Behavior-preserving swaps. Each raw `<input>`/`<textarea>` becomes the matching primitive, keeping every behavioral prop and a11y handle (`id`, `aria-label`, `placeholder`, `aria-describedby`, `rows`, `maxLength`, `disabled`, `value`/`onChange`). Special styling is kept via `className` (`font-mono`, `resize-none`). The inline border/bg/shadow/focus classes are dropped (the primitive supplies them).

**Tech Stack:** React 19, TypeScript, Vite 8, Tailwind v4, Vitest + Testing Library.

## Global Constraints

- **Behavior-preserving** except ONE intended change: the Assistant message input height `h-10` → `h-9` (Input default `md`), which aligns it with the adjacent Send button.
- **Preserve every a11y handle** exactly (`id`, `aria-label`, `placeholder`, `aria-describedby`, `rows`, `maxLength`, `disabled`) so existing screen tests and a11y are unaffected.
- **Keep special styling** via `className`: `font-mono` (DbtModels SQL), `resize-none` (NLChartPanel prompt).
- **No new props/tokens.** Reuse the hardened `Input` (`@/components/ui/input`) and `Textarea` (`@/components/ui/textarea`).
- The working tree has **unrelated user WIP** (dialog.tsx, Builder.tsx, backend, `docs/FRONTEND.md`, configs). Each task `git add`s ONLY its files; never `git add -A`/`.`. `docs/FRONTEND.md` is pre-modified → Task 5 is controller-handled.
- Imports use the `@/` alias. Add the `Input`/`Textarea` import only if the file doesn't already have it; don't duplicate.
- The adoption marker class (from the primitives' shared `focusRing`) is `focus-visible:ring-offset-2` — the old hand-rolled `focus-visible:ring-1` lacked it. Tests assert this to confirm adoption.
- Run commands from `d:\Novasight_v2\frontend`. Commit after each task.

---

### Task 1: NLChartPanel prompt → Textarea

**Files:**
- Modify: `frontend/src/components/chart/NLChartPanel.tsx`
- Test: `frontend/src/test/nlChartPanel.test.tsx` (extend)

**Interfaces:**
- Consumes: `Textarea` from `@/components/ui/textarea`.
- Produces: no API change to `NLChartPanel`.

- [ ] **Step 1: Write the failing test**

In `frontend/src/test/nlChartPanel.test.tsx`, append a new describe block at the end of the file:

```tsx
describe("NLChartPanel — hardened textarea", () => {
  it("uses the shared Textarea primitive (focus ring + resize-none)", () => {
    mockUseNLChart.mockReturnValue(
      // @ts-expect-error: partial mock
      makeMutationReturn({})
    );
    render(<NLChartPanel />);
    const textarea = screen.getByRole("textbox", { name: /chart description/i });
    expect(textarea).toHaveClass("focus-visible:ring-offset-2");
    expect(textarea).toHaveClass("resize-none");
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pnpm exec vitest run src/test/nlChartPanel.test.tsx`
Expected: the new test FAILS (current `<textarea>` has `focus-visible:ring-1`, not `ring-offset-2`).

- [ ] **Step 3: Swap the control**

In `frontend/src/components/chart/NLChartPanel.tsx`:

(a) Add the import near the other `@/components/ui/*` imports:

```tsx
import { Textarea } from "@/components/ui/textarea";
```

(b) Replace the `<textarea … />` block (currently lines ~133–143) with:

```tsx
            <Textarea
              id="nl-chart-prompt"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="e.g. total sales by region as a bar chart"
              maxLength={MAX_CHARS}
              rows={3}
              disabled={isPending}
              aria-describedby="nl-chart-hint"
              className="resize-none"
            />
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pnpm exec vitest run src/test/nlChartPanel.test.tsx`
Expected: PASS (all existing tests + the new one — existing tests query the textarea by its preserved label/role, so they stay green).

- [ ] **Step 5: Type check**

Run: `pnpm exec tsc --noEmit`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/chart/NLChartPanel.tsx frontend/src/test/nlChartPanel.test.tsx
git commit -m "refactor(ui): NLChartPanel prompt uses hardened Textarea"
```

---

### Task 2: Assistant message input → Input

**Files:**
- Modify: `frontend/src/pages/Assistant.tsx`
- Test: `frontend/src/test/assistant.test.tsx` (extend)

**Interfaces:**
- Consumes: `Input` from `@/components/ui/input`.
- Produces: no API change to `Assistant`.

- [ ] **Step 1: Write the failing test**

In `frontend/src/test/assistant.test.tsx`, add inside the existing `describe("Assistant page", …)` block:

```tsx
  it("uses the shared Input primitive for the message box", () => {
    renderAssistant();
    const message = screen.getByRole("textbox", { name: "Message" });
    expect(message).toHaveClass("focus-visible:ring-offset-2");
  });
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pnpm exec vitest run src/test/assistant.test.tsx`
Expected: the new test FAILS (current `<input>` has `focus-visible:ring-1`, not `ring-offset-2`).

- [ ] **Step 3: Swap the control**

In `frontend/src/pages/Assistant.tsx`:

(a) Add the import near the other `@/components/ui/*` imports (e.g. next to the `Button` import):

```tsx
import { Input } from "@/components/ui/input";
```

(b) Replace the `<input … />` block (currently lines ~208–215) with:

```tsx
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask, chart, or summarize…"
          aria-label="Message"
          maxLength={2000}
        />
```

(`Input` is `w-full` by default; its height is the `h-9` md default — intentionally aligning with the adjacent `h-9` Send button.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `pnpm exec vitest run src/test/assistant.test.tsx`
Expected: PASS (existing tests unaffected; they drive the page via suggestion chips, not the input).

- [ ] **Step 5: Type check**

Run: `pnpm exec tsc --noEmit`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/Assistant.tsx frontend/src/test/assistant.test.tsx
git commit -m "refactor(ui): Assistant message box uses hardened Input"
```

---

### Task 3: DbtModels SQL field → Textarea

**Files:**
- Modify: `frontend/src/pages/DbtModels.tsx`
- Test: `frontend/src/test/dbtModels.test.tsx` (extend)

**Interfaces:**
- Consumes: `Textarea` from `@/components/ui/textarea` (`Input` is already imported in this file).
- Produces: no API change to `DbtModels`.

- [ ] **Step 1: Write the failing test**

In `frontend/src/test/dbtModels.test.tsx`, add inside the existing `describe("DbtModels wizard", …)` block:

```tsx
  it("uses the shared Textarea primitive for the SQL field (mono + focus ring)", () => {
    render(<DbtModels />);
    fireEvent.click(screen.getAllByRole("button", { name: /new model/i })[0]);
    const sql = document.querySelector("#dm-sql")!;
    expect(sql).toHaveClass("focus-visible:ring-offset-2");
    expect(sql).toHaveClass("font-mono");
  });
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pnpm exec vitest run src/test/dbtModels.test.tsx`
Expected: the new test FAILS (current `<textarea id="dm-sql">` has `focus-visible:ring-1`, not `ring-offset-2`).

- [ ] **Step 3: Swap the control**

In `frontend/src/pages/DbtModels.tsx`:

(a) Add the `Textarea` import next to the existing `Input` import:

```tsx
import { Textarea } from "@/components/ui/textarea";
```

(b) Replace the `<textarea id="dm-sql" … />` block (currently lines ~406–413) with:

```tsx
            <Textarea
              id="dm-sql"
              value={sql}
              onChange={(e) => setSql(e.target.value)}
              rows={6}
              placeholder="select region, sum(amount) as total from {{ ref('stg_orders') }} group by 1"
              className="font-mono"
            />
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pnpm exec vitest run src/test/dbtModels.test.tsx`
Expected: PASS (existing tests query `#dm-sql` by id, which is preserved, so they stay green).

- [ ] **Step 5: Type check**

Run: `pnpm exec tsc --noEmit`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/DbtModels.tsx frontend/src/test/dbtModels.test.tsx
git commit -m "refactor(ui): DbtModels SQL field uses hardened Textarea"
```

---

### Task 4: DashboardDetail add-object text → Textarea

**Files:**
- Modify: `frontend/src/pages/DashboardDetail.tsx`

**Interfaces:**
- Consumes: `Textarea` from `@/components/ui/textarea` (`Input` is already imported in this file).
- Produces: no API change.

> **Note:** the add-object form (kind = text/markdown) is gated behind UI state in a heavy page (route params + dashboard query). It has no isolated test harness, so this swap is verified by `tsc` + the full suite staying green (Task 5) — it is an identical, behavior-preserving pattern to Tasks 1–3, which ARE asserted. No new test file is created for it.

- [ ] **Step 1: Swap the control**

In `frontend/src/pages/DashboardDetail.tsx`:

(a) Add the `Textarea` import next to the existing `Input` import:

```tsx
import { Textarea } from "@/components/ui/textarea";
```

(b) Replace the `<textarea id="ao-text" … />` block (currently lines ~359–366) with:

```tsx
            <Textarea
              id="ao-text"
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={5}
              placeholder={kind === "markdown" ? "## Heading\n**bold** text" : "Your note…"}
            />
```

- [ ] **Step 2: Type check**

Run: `pnpm exec tsc --noEmit`
Expected: PASS.

- [ ] **Step 3: Run the dashboard-related suites to confirm no regression**

Run: `pnpm exec vitest run src/test/dashboardDetailFilters.test.tsx src/test/dashboardCardTile.test.tsx src/test/dashboardGrid.test.tsx`
Expected: PASS (the `Textarea` swap preserves `id`/`value`/`onChange`/`rows`/`placeholder`; these suites exercise DashboardDetail wiring).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/DashboardDetail.tsx
git commit -m "refactor(ui): DashboardDetail add-object text uses hardened Textarea"
```

---

### Task 5: Docs + full-gate verification (controller-executed)

**Files:**
- Modify: `docs/FRONTEND.md`

> **Controller note:** `docs/FRONTEND.md` is in the user's uncommitted WIP. Executed by the controller (not a subagent): stash the WIP for that file, append the docs, commit only the docs change, then `git stash pop` to restore the WIP — same approach as slices 1 and 2.

- [ ] **Step 1: Update the docs**

In `docs/FRONTEND.md`, under the `### Control contract (core primitives)` subsection, append a bullet:

```markdown
- **Pages consume the primitives:** the chat box (`Assistant`), the NL-chart
  prompt (`NLChartPanel`), the dbt SQL field (`DbtModels`), and the dashboard
  add-object text (`DashboardDetail`) use the hardened `Input`/`Textarea` — no
  more hand-rolled `focus-visible:ring-1` text controls in those screens.
```

- [ ] **Step 2: Run the FULL gate first-hand**

Run: `pnpm exec tsc --noEmit`
Expected: PASS (0 errors).

Run: `pnpm lint`
Expected: PASS (0 errors; warning count unchanged from the 44 baseline).

Run: `pnpm test`
Expected: PASS — all suites green, including the extended `nlChartPanel`, `assistant`, `dbtModels` tests.

> If a pre-existing test asserted an old hand-rolled class (e.g. queried by a brittle class selector), update it to the primitive's behavior — do not weaken it.

- [ ] **Step 3: Commit**

```bash
git add docs/FRONTEND.md
git commit -m "docs(frontend): pages now consume the hardened Input/Textarea"
```

---

## Self-Review

**Spec coverage:**
- NLChartPanel textarea → Textarea (resize-none) → Task 1. ✓
- Assistant input → Input (h-9) → Task 2. ✓
- DbtModels SQL textarea → Textarea (font-mono) → Task 3. ✓
- DashboardDetail add-object textarea → Textarea → Task 4. ✓
- Docs + full gate (first-hand) → Task 5. ✓
- Out of scope (checkboxes, file/number inputs, compact filter input, new props) → not touched. ✓
- Assistant h-10→h-9 behavior change → flagged in Global Constraints + Task 2. ✓

**Placeholder scan:** No TBD/TODO; every code/test step has complete code + an explicit run command and expected result. The DashboardDetail "no isolated test" decision is stated with its rationale and an alternative verification (tsc + dashboard suites), not a vague gap. ✓

**Type consistency:**
- `Textarea` imported from `@/components/ui/textarea` (Tasks 1/3/4); `Input` from `@/components/ui/input` (Task 2). ✓
- Adoption marker `focus-visible:ring-offset-2` matches the primitives' shared `focusRing` (from slices 1–2). ✓
- Each swap preserves the exact handle the existing tests query: NLChartPanel role/label "chart description"; Assistant aria-label "Message"; DbtModels `#dm-sql` id; DashboardDetail `#ao-text` id. ✓
- Special classes preserved: `resize-none` (Task 1), `font-mono` (Task 3). ✓

No gaps found.
