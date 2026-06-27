# Component Hardening Slice 5 — Layout z-index / Elevation Tokens Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Map the hardcoded z-index / heavy-shadow values in the layout chrome and floating overlays to the `--z-*` / `--elevation-*` tokens, for one global stacking/elevation source of truth.

**Architecture:** Pure className edits — replace each hardcoded utility with the arbitrary-value token utility (`z-[var(--z-…)]`, `shadow-[var(--elevation-…)]`). No structural, prop, or logic changes. No new tokens (all exist in `index.css` from slice 1).

**Tech Stack:** React 19, TypeScript, Vite 8, Tailwind v4, Vitest + Testing Library.

## Global Constraints

- **className-only.** Change ONLY the named utility classes below. Do not touch structure, props, roles, or logic. No new tokens.
- **The exact mappings** (nothing else changes in each className string):
  - `z-30` (TopBar sticky) → `z-[var(--z-sticky)]`
  - `z-50` (Sidebar overlay) → `z-[var(--z-overlay)]`
  - `focus:z-50` (AppShell skip-nav) → `focus:z-[var(--z-overlay)]`
  - `z-30` (ChartActionsMenu) → `z-[var(--z-dropdown)]`; `shadow-md` → `shadow-[var(--elevation-2)]`
  - `z-20` (TileSizeControl) → `z-[var(--z-dropdown)]`; `shadow-md` → `shadow-[var(--elevation-2)]`
  - `shadow-2xl` (Sidebar drawer) → `shadow-[var(--elevation-4)]`
  - `shadow-lg` (SemanticQueryBuilder drag preview) → `shadow-[var(--elevation-3)]`
- **Excluded:** `DashboardCardTile.tsx:254` `z-10`; `dialog.tsx` (user WIP) — do NOT touch.
- **Stacking is visual; not jsdom-testable.** The two overlay popovers get adoption assertions (token classes present); the rest are verified by `tsc`, a completeness grep, existing suites staying green, and the production build. Actual visual layering requires a **manual browser smoke** (a user step, recorded in docs).
- The working tree has **unrelated user WIP** (dialog.tsx, Builder.tsx, backend, `docs/FRONTEND.md`, configs). Each task `git add`s ONLY its files; never `git add -A`/`.`. `docs/FRONTEND.md` is pre-modified → Task 3 is controller-handled.
- Run commands from `d:\Novasight_v2\frontend`. `@/` alias → `frontend/src/`. Commit after each task.

---

### Task 1: Overlay popovers — ChartActionsMenu + TileSizeControl

**Files:**
- Modify: `frontend/src/components/chart/ChartActionsMenu.tsx`
- Modify: `frontend/src/components/dashboard/TileSizeControl.tsx`
- Test: `frontend/src/test/chartActionsMenu.test.tsx`, `frontend/src/test/tileSizeControl.test.tsx`

**Interfaces:**
- Consumes: tokens `--z-dropdown`, `--elevation-2`.
- Produces: no API change; both popovers token-driven.

- [ ] **Step 1: Write the failing tests**

In `frontend/src/test/chartActionsMenu.test.tsx`, add inside the `describe("ChartActionsMenu", …)` block:

```tsx
  it("renders the menu with token-driven stacking + elevation", () => {
    render(<ChartActionsMenu spec={specOfType("bar")} data={data} title="Sales" />);
    fireEvent.click(screen.getByRole("button", { name: /chart actions/i }));
    const menu = screen.getByRole("menu");
    expect(menu).toHaveClass("z-[var(--z-dropdown)]");
    expect(menu).toHaveClass("shadow-[var(--elevation-2)]");
  });
```

In `frontend/src/test/tileSizeControl.test.tsx`, add inside the `describe("TileSizeControl", …)` block:

```tsx
  it("renders the panel with token-driven stacking + elevation", () => {
    render(<TileSizeControl title="Revenue" w={6} h={4} onResize={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Size of Revenue" }));
    const panel = screen.getByRole("group");
    expect(panel).toHaveClass("z-[var(--z-dropdown)]");
    expect(panel).toHaveClass("shadow-[var(--elevation-2)]");
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pnpm exec vitest run src/test/chartActionsMenu.test.tsx src/test/tileSizeControl.test.tsx`
Expected: the two new tests FAIL (current panels have `z-30`/`z-20` + `shadow-md`, not the token classes).

- [ ] **Step 3: Swap the classes**

In `frontend/src/components/chart/ChartActionsMenu.tsx`, the `role="menu"` panel className (currently
`"absolute right-0 z-30 mt-1 w-44 rounded-md border bg-popover p-1 shadow-md"`) becomes:

```tsx
            className="absolute right-0 z-[var(--z-dropdown)] mt-1 w-44 rounded-md border bg-popover p-1 shadow-[var(--elevation-2)]"
```

In `frontend/src/components/dashboard/TileSizeControl.tsx`, the `role="group"` panel className (currently
`"absolute right-0 z-20 mt-1 w-44 space-y-2 rounded-md border bg-popover p-3 text-popover-foreground shadow-md"`) becomes:

```tsx
          className="absolute right-0 z-[var(--z-dropdown)] mt-1 w-44 space-y-2 rounded-md border bg-popover p-3 text-popover-foreground shadow-[var(--elevation-2)]"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pnpm exec vitest run src/test/chartActionsMenu.test.tsx src/test/tileSizeControl.test.tsx`
Expected: PASS (the two new tests + all existing tests in both files — the swap is className-only, behavior unchanged).

- [ ] **Step 5: Type check**

Run: `pnpm exec tsc --noEmit`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/chart/ChartActionsMenu.tsx frontend/src/components/dashboard/TileSizeControl.tsx frontend/src/test/chartActionsMenu.test.tsx frontend/src/test/tileSizeControl.test.tsx
git commit -m "refactor(ui): chart/tile popovers use z-index + elevation tokens"
```

---

### Task 2: Layout chrome + drag preview tokens

**Files:**
- Modify: `frontend/src/components/layout/TopBar.tsx`
- Modify: `frontend/src/components/layout/Sidebar.tsx`
- Modify: `frontend/src/components/layout/AppShell.tsx`
- Modify: `frontend/src/components/chart/SemanticQueryBuilder.tsx`

**Interfaces:**
- Consumes: tokens `--z-sticky`, `--z-overlay`, `--elevation-4`, `--elevation-3`.
- Produces: no API change.

> **Note:** these are not unit-assertable (TopBar/Sidebar stacking; the drag preview only renders mid-drag). Verified by the completeness grep, `tsc`, and existing suites staying green; visual layering is checked in Task 3's manual smoke.

- [ ] **Step 1: Apply the class swaps**

- `TopBar.tsx` — in the `<header>` className, replace `z-30` with `z-[var(--z-sticky)]` (keep `sticky top-0` and everything else):
  ```tsx
  className="sticky top-0 z-[var(--z-sticky)] flex h-14 items-center gap-2 border-b border-border/60 bg-background/70 px-3 backdrop-blur md:px-5"
  ```
- `Sidebar.tsx` — the mobile overlay wrapper: replace `z-50` with `z-[var(--z-overlay)]`:
  ```tsx
  <div className="fixed inset-0 z-[var(--z-overlay)] md:hidden">
  ```
  and the drawer `<aside>`: replace `shadow-2xl` with `shadow-[var(--elevation-4)]`:
  ```tsx
  <aside className="absolute left-0 top-0 flex h-full w-64 flex-col gap-4 border-r bg-card p-3 shadow-[var(--elevation-4)] animate-in-up">
  ```
- `AppShell.tsx` — the skip-nav link: replace `focus:z-50` with `focus:z-[var(--z-overlay)]`:
  ```tsx
  className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-[var(--z-overlay)] focus:rounded-md focus:bg-primary focus:px-3 focus:py-2 focus:text-primary-foreground"
  ```
- `SemanticQueryBuilder.tsx` — the drag-preview `<span>`: replace `shadow-lg` with `shadow-[var(--elevation-3)]`:
  ```tsx
  <span className="rounded-md border bg-card px-2 py-1 text-xs shadow-[var(--elevation-3)]">{dragLabel}</span>
  ```

- [ ] **Step 2: Confirm completeness (the old values are gone)**

Run: `grep -nE 'z-30|z-50|shadow-2xl' src/components/layout/TopBar.tsx src/components/layout/Sidebar.tsx src/components/layout/AppShell.tsx; grep -n 'shadow-lg' src/components/chart/SemanticQueryBuilder.tsx`
Expected: NO output (every targeted value is now a token utility).

- [ ] **Step 3: Type check + regression suites**

Run: `pnpm exec tsc --noEmit`
Expected: PASS.

Run: `pnpm exec vitest run src/test/sidebarNav.test.tsx src/test/builderSemantic.test.tsx src/test/builderLoadSpec.test.tsx`
Expected: PASS (className-only swaps; these suites render Sidebar/TopBar and the builder).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/layout/TopBar.tsx frontend/src/components/layout/Sidebar.tsx frontend/src/components/layout/AppShell.tsx frontend/src/components/chart/SemanticQueryBuilder.tsx
git commit -m "refactor(ui): layout chrome + drag preview use z-index/elevation tokens"
```

---

### Task 3: Docs + full-gate + prod build (controller-executed)

**Files:**
- Modify: `docs/FRONTEND.md`

> **Controller note:** `docs/FRONTEND.md` is in the user's uncommitted WIP. Executed by the controller: stash the WIP for that file, append the docs, commit only the docs change, then `git stash pop` — same approach as slices 1–4.

- [ ] **Step 1: Update the docs**

In `docs/FRONTEND.md`, under the `### Control contract (core primitives)` subsection, append a bullet:

```markdown
- **Layout stacking + elevation:** the sticky topbar, mobile sidebar overlay,
  skip-nav, and the chart/tile popovers use the `--z-*` / `--elevation-*` tokens
  (one global order: dropdown < sticky < overlay < modal < popover < toast),
  rather than hardcoded `z-30`/`z-50`/`shadow-md` (slice 5). Visual layering is
  validated by a manual browser smoke (jsdom can't test stacking).
```

- [ ] **Step 2: Run the FULL gate first-hand**

Run: `pnpm exec tsc --noEmit`
Expected: PASS (0 errors).

Run: `pnpm lint`
Expected: PASS (0 errors; warning count unchanged from the 44 baseline).

Run: `pnpm test`
Expected: PASS — all suites green, including the two new popover adoption tests.

Run: `pnpm build`
Expected: build succeeds (token arbitrary-value classes compile; the prod CSS includes the `--z-*`/`--elevation-*`-driven utilities).

- [ ] **Step 3: Commit**

```bash
git add docs/FRONTEND.md
git commit -m "docs(frontend): layout/overlay stacking + elevation use tokens"
```

- [ ] **Step 4: Record the manual smoke for the user**

In the completion summary, tell the user to do a ~1-minute browser smoke: open the
mobile nav (sidebar overlay should cover the topbar), confirm the sticky topbar
stays above page content on scroll, and open a chart-actions menu + a tile-size
popover (both should float above their cards). This is the only check jsdom can't
perform.

---

## Self-Review

**Spec coverage:**
- ChartActionsMenu + TileSizeControl z-index + elevation (with adoption tests) → Task 1. ✓
- TopBar z-sticky, Sidebar z-overlay + elevation-4, AppShell skip-nav z-overlay, SemanticQueryBuilder elevation-3 → Task 2 (completeness grep). ✓
- Docs + full gate + prod build + manual-smoke note → Task 3. ✓
- Excluded DashboardCardTile z-10 + dialog.tsx → untouched. ✓
- Single global order documented. ✓

**Placeholder scan:** No TBD/TODO; every swap has the exact before/after className, and every step an explicit command + expected result. The non-asserted Task-2 swaps state their rationale + alternative verification (grep + suites + build). ✓

**Type consistency:**
- Token utilities used consistently: `z-[var(--z-dropdown)]` / `z-[var(--z-sticky)]` / `z-[var(--z-overlay)]`; `shadow-[var(--elevation-2)]` / `-3` / `-4`. All reference tokens defined in slice 1's `index.css`. ✓
- Adoption assertions target the styled element: ChartActionsMenu `role="menu"` (carries the className), TileSizeControl `role="group"` (carries the className) — both confirmed from source. ✓

No gaps found.
