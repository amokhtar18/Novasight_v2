# Component Hardening Slice 2 — Contract Rollout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Roll slice-1's shared `focusRing` and the z-index/elevation tokens out to the remaining interactive primitives (switch, tabs, dropdown-menu, badge, checkbox) so the whole system shares one focus ring and one stacking/elevation scale.

**Architecture:** A mostly behavior-preserving consistency pass. Each in-scope primitive swaps its inline `focus-visible:*` classes for the shared `focusRing` constant from `@/components/ui/_shared`, and the overlay/tab primitives adopt the existing `--z-*` / `--elevation-*` / `--control-h-*` tokens via Tailwind arbitrary-value classes. No new tokens, no new props.

**Tech Stack:** React 19, TypeScript, Vite 8, Tailwind CSS v4, class-variance-authority, Vitest + Testing Library.

## Global Constraints

- **Reuse only** slice-1 artifacts: `focusRing` from `frontend/src/components/ui/_shared.ts` and the tokens already in `frontend/src/index.css` (`--control-h-md`, `--elevation-1`, `--elevation-3`, `--z-dropdown`). **No new tokens, no new props/variants** (YAGNI).
- **Behavior-preserving** except ONE intended change: the dropdown panel stacking moves `z-50` → `z-[var(--z-dropdown)]` (50 → 1000). No current consumer pins `z-50`.
- **`dialog.tsx` is OUT of scope** — it is in the user's uncommitted WIP; do not touch it.
- Dropdown **menu items** keep their `bg-accent` focus highlight (correct for `role=menuitem`); do NOT give them a ring.
- **Additive / no public API change** to any primitive — existing consumers must still compile (`pnpm exec tsc --noEmit` clean).
- The working tree has **unrelated user WIP** (dialog.tsx, Builder.tsx, backend files, `docs/FRONTEND.md`, configs). Each task `git add`s ONLY its own files; never `git add -A`/`.`. `docs/FRONTEND.md` is pre-modified → its task is controller-handled (Task 5).
- Imports use the `@/` alias; `cn` from `@/lib/cn`.
- Run commands from `d:\Novasight_v2\frontend`. Commit after each task.
- The `focusRing` constant value (for test assertions) is:
  `"outline-none ring-offset-background focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"` — so `focus-visible:ring-offset-2` is the marker class that the old inline rings (on checkbox/badge/tabs/dropdown) lacked.

---

### Task 1: Adopt `focusRing` in checkbox, badge, switch

**Files:**
- Modify: `frontend/src/components/ui/checkbox.tsx`
- Modify: `frontend/src/components/ui/badge.tsx`
- Modify: `frontend/src/components/ui/switch.tsx`
- Test: `frontend/src/test/checkbox.test.tsx`, `frontend/src/test/badge.test.tsx`, `frontend/src/test/switch.test.tsx`

**Interfaces:**
- Consumes: `focusRing` from `@/components/ui/_shared`.
- Produces: no API change — three primitives now render the shared focus ring.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/test/checkbox.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { Checkbox } from "@/components/ui/checkbox";

describe("Checkbox", () => {
  it("uses the shared focus ring (offset)", () => {
    render(<Checkbox aria-label="agree" />);
    expect(screen.getByLabelText("agree")).toHaveClass("focus-visible:ring-offset-2");
  });
});
```

Create `frontend/src/test/badge.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { Badge } from "@/components/ui/badge";

describe("Badge", () => {
  it("uses the shared focus ring (offset)", () => {
    render(<Badge>New</Badge>);
    expect(screen.getByText("New")).toHaveClass("focus-visible:ring-offset-2");
  });

  it("keeps its semantic variants", () => {
    render(<Badge variant="success">ok</Badge>);
    expect(screen.getByText("ok")).toHaveClass("text-success");
  });
});
```

Create `frontend/src/test/switch.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { Switch } from "@/components/ui/switch";

describe("Switch", () => {
  it("uses the shared focus ring (offset)", () => {
    render(<Switch checked={false} onCheckedChange={() => {}} aria-label="toggle" />);
    expect(screen.getByRole("switch")).toHaveClass("focus-visible:ring-offset-2");
  });

  it("toggles on click (behavior preserved)", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<Switch checked={false} onCheckedChange={onChange} aria-label="toggle" />);
    await user.click(screen.getByRole("switch"));
    expect(onChange).toHaveBeenCalledWith(true);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pnpm exec vitest run src/test/checkbox.test.tsx src/test/badge.test.tsx src/test/switch.test.tsx`
Expected: the three `focus ring (offset)` tests FAIL (current inline rings on checkbox/badge lack `ring-offset-2`; switch has it inline but not via the shared constant yet — assertion still passes for switch, so only checkbox+badge offset tests fail. The toggle/variant tests pass). At least the checkbox and badge offset assertions must be RED.

- [ ] **Step 3: Update checkbox.tsx**

Replace the full contents of `frontend/src/components/ui/checkbox.tsx`:

```tsx
import * as React from "react";
import { cn } from "@/lib/cn";
import { focusRing } from "@/components/ui/_shared";

export type CheckboxProps = React.InputHTMLAttributes<HTMLInputElement>;

/**
 * Styled native checkbox — accessible by default (keyboard + screen reader) and
 * consistent with the project's hand-rolled primitives (see Select/Dialog), without
 * pulling in a popup/primitive dependency. Wrap in a <label> for the control text.
 */
export const Checkbox = React.forwardRef<HTMLInputElement, CheckboxProps>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      type="checkbox"
      className={cn(
        "h-4 w-4 shrink-0 cursor-pointer rounded border-input accent-primary",
        focusRing,
        "disabled:cursor-not-allowed disabled:opacity-50",
        className
      )}
      {...props}
    />
  )
);
Checkbox.displayName = "Checkbox";
```

- [ ] **Step 4: Update badge.tsx**

In `frontend/src/components/ui/badge.tsx`, add the import and replace the CVA base string. Change the imports block to:

```tsx
import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/cn";
import { focusRing } from "@/components/ui/_shared";
```

Replace the `cva(...)` base (first argument) so the inline focus classes become the shared constant:

```tsx
const badgeVariants = cva(
  cn(
    "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors",
    focusRing
  ),
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary/15 text-primary",
        secondary: "border-transparent bg-secondary text-secondary-foreground",
        outline: "border-border text-foreground",
        success: "border-transparent bg-success/15 text-success",
        warning: "border-transparent bg-warning/15 text-warning",
        danger: "border-transparent bg-destructive/15 text-destructive",
        info: "border-transparent bg-info/15 text-info",
      },
    },
    defaultVariants: { variant: "default" },
  }
);
```

- [ ] **Step 5: Update switch.tsx**

In `frontend/src/components/ui/switch.tsx`, add the import and swap the inline focus classes for `focusRing`. Add to the imports:

```tsx
import { cn } from "@/lib/cn";
import { focusRing } from "@/components/ui/_shared";
```

Replace the button `className` `cn(...)` call with:

```tsx
      className={cn(
        "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors disabled:opacity-50",
        focusRing,
        checked ? "bg-primary" : "bg-input",
        className
      )}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pnpm exec vitest run src/test/checkbox.test.tsx src/test/badge.test.tsx src/test/switch.test.tsx`
Expected: PASS (4 tests total: checkbox 1, badge 2, switch 2 → 5 tests; all pass).

- [ ] **Step 7: Type check**

Run: `pnpm exec tsc --noEmit`
Expected: PASS (no consumer broke).

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/ui/checkbox.tsx frontend/src/components/ui/badge.tsx frontend/src/components/ui/switch.tsx frontend/src/test/checkbox.test.tsx frontend/src/test/badge.test.tsx frontend/src/test/switch.test.tsx
git commit -m "refactor(ui): adopt shared focusRing in checkbox/badge/switch"
```

---

### Task 2: Tabs — focusRing + control-height + elevation tokens

**Files:**
- Modify: `frontend/src/components/ui/tabs.tsx`
- Test: `frontend/src/test/tabs.test.tsx`

**Interfaces:**
- Consumes: `focusRing` from `@/components/ui/_shared`; tokens `--control-h-md`, `--elevation-1`.
- Produces: no API change — `TabsList`/`TabsTrigger` now token-driven.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/test/tabs.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";

function Harness({ value = "a" }: { value?: string }) {
  return (
    <Tabs value={value} onValueChange={() => {}}>
      <TabsList>
        <TabsTrigger value="a">A</TabsTrigger>
        <TabsTrigger value="b">B</TabsTrigger>
      </TabsList>
      <TabsContent value="a">Panel A</TabsContent>
      <TabsContent value="b">Panel B</TabsContent>
    </Tabs>
  );
}

describe("Tabs", () => {
  it("TabsList uses the control-height token", () => {
    render(<Harness />);
    expect(screen.getByRole("tablist")).toHaveClass("h-[var(--control-h-md)]");
  });

  it("TabsTrigger uses the shared focus ring (offset)", () => {
    render(<Harness />);
    expect(screen.getByRole("tab", { name: "A" })).toHaveClass("focus-visible:ring-offset-2");
  });

  it("active TabsTrigger uses the elevation-1 token shadow", () => {
    render(<Harness value="a" />);
    expect(screen.getByRole("tab", { name: "A" })).toHaveClass("shadow-[var(--elevation-1)]");
  });

  it("shows only the active panel (behavior preserved)", () => {
    render(<Harness value="a" />);
    expect(screen.getByText("Panel A")).toBeInTheDocument();
    expect(screen.queryByText("Panel B")).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pnpm exec vitest run src/test/tabs.test.tsx`
Expected: FAIL — the token-class assertions fail (current `h-9`, inline ring, `shadow-sm`).

- [ ] **Step 3: Update tabs.tsx**

In `frontend/src/components/ui/tabs.tsx`:

(a) Add the import after the existing `cn` import:

```tsx
import { focusRing } from "@/components/ui/_shared";
```

(b) In `TabsList`, change the `cn(...)` first string — replace `h-9` with the token:

```tsx
      className={cn(
        "inline-flex h-[var(--control-h-md)] items-center justify-center gap-1 rounded-lg bg-muted/60 p-1 text-muted-foreground",
        className
      )}
```

(c) In `TabsTrigger`, replace the `className={cn(...)}` block with:

```tsx
      className={cn(
        "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md px-3 py-1 text-sm font-medium transition-all",
        focusRing,
        selected
          ? "bg-card text-foreground shadow-[var(--elevation-1)]"
          : "text-muted-foreground hover:text-foreground",
        className
      )}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pnpm exec vitest run src/test/tabs.test.tsx`
Expected: PASS (4 tests).

- [ ] **Step 5: Type check**

Run: `pnpm exec tsc --noEmit`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ui/tabs.tsx frontend/src/test/tabs.test.tsx
git commit -m "refactor(ui): Tabs focusRing + control-height/elevation tokens"
```

---

### Task 3: Dropdown menu — focusRing + z-index/elevation tokens

**Files:**
- Modify: `frontend/src/components/ui/dropdown-menu.tsx`
- Test: `frontend/src/test/dropdownMenu.test.tsx`

**Interfaces:**
- Consumes: `focusRing` from `@/components/ui/_shared`; tokens `--z-dropdown`, `--elevation-3`.
- Produces: no API change — trigger uses the shared ring; panel uses token stacking + elevation.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/test/dropdownMenu.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { DropdownMenu, DropdownItem } from "@/components/ui/dropdown-menu";

function Harness() {
  return (
    <DropdownMenu trigger={<span>Open</span>} label="menu">
      <DropdownItem>Item</DropdownItem>
    </DropdownMenu>
  );
}

describe("DropdownMenu", () => {
  it("trigger uses the shared focus ring (offset)", () => {
    render(<Harness />);
    expect(screen.getByRole("button", { name: "menu" })).toHaveClass(
      "focus-visible:ring-offset-2"
    );
  });

  it("opens the menu with token-driven stacking + elevation", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "menu" }));
    const menu = screen.getByRole("menu");
    expect(menu).toHaveClass("z-[var(--z-dropdown)]");
    expect(menu).toHaveClass("shadow-[var(--elevation-3)]");
  });

  it("closes on item activation (behavior preserved)", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "menu" }));
    await user.click(screen.getByRole("menuitem", { name: "Item" }));
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pnpm exec vitest run src/test/dropdownMenu.test.tsx`
Expected: FAIL — current trigger lacks `ring-offset-2`; panel has `z-50`/`shadow-xl`, not the token classes.

- [ ] **Step 3: Update dropdown-menu.tsx**

In `frontend/src/components/ui/dropdown-menu.tsx`:

(a) Add the import after the existing `cn` import:

```tsx
import { focusRing } from "@/components/ui/_shared";
```

(b) Replace the trigger `<button>`'s `className` (the inline focus string) with:

```tsx
        className={cn("inline-flex items-center rounded-md", focusRing)}
```

(c) Replace the panel `<div role="menu">`'s `cn(...)` first string with the token version (only `z-50` → token and `shadow-xl` → token change; the rest is unchanged):

```tsx
          className={cn(
            "absolute z-[var(--z-dropdown)] mt-2 min-w-44 overflow-hidden rounded-lg border bg-popover p-1 text-popover-foreground shadow-[var(--elevation-3)] animate-in-up",
            align === "end" ? "right-0" : "left-0",
            className
          )}
```

(Leave `DropdownItem`, `DropdownLabel`, `DropdownSeparator` unchanged — item focus highlight via `bg-accent` is correct for menuitems.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `pnpm exec vitest run src/test/dropdownMenu.test.tsx`
Expected: PASS (3 tests).

- [ ] **Step 5: Type check**

Run: `pnpm exec tsc --noEmit`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ui/dropdown-menu.tsx frontend/src/test/dropdownMenu.test.tsx
git commit -m "refactor(ui): DropdownMenu focusRing + z-index/elevation tokens"
```

---

### Task 4: Extend the gallery with the rolled-out primitives

**Files:**
- Modify: `frontend/src/pages/dev/ComponentsGallery.tsx`
- Modify: `frontend/src/test/componentsGallery.test.tsx`

**Interfaces:**
- Consumes: `Switch`, `Tabs`/`TabsList`/`TabsTrigger`/`TabsContent`, `DropdownMenu`/`DropdownItem`, `Badge`, `Checkbox`.
- Produces: gallery sections for the rolled-out primitives.

- [ ] **Step 1: Write the failing test (extend the existing gallery test)**

In `frontend/src/test/componentsGallery.test.tsx`, add inside the existing `describe("ComponentsGallery", …)` block:

```tsx
  it("renders the rolled-out primitive sections", () => {
    render(<ComponentsGallery />);
    for (const name of ["Switch", "Tabs", "Dropdown", "Badge", "Checkbox"]) {
      expect(
        screen.getByRole("heading", { name: new RegExp(`^${name}$`, "i") })
      ).toBeInTheDocument();
    }
  });
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pnpm exec vitest run src/test/componentsGallery.test.tsx`
Expected: FAIL — those section headings don't exist yet.

- [ ] **Step 3: Extend ComponentsGallery.tsx**

(a) Add these imports alongside the existing primitive imports at the top of `frontend/src/pages/dev/ComponentsGallery.tsx`:

```tsx
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { DropdownMenu, DropdownItem } from "@/components/ui/dropdown-menu";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Button } from "@/components/ui/button";
```

(If `Button` is already imported in the file, do not duplicate the import.)

(b) Add interactive state at the top of the `ComponentsGallery` function body (just inside the function, before the `return`):

```tsx
  const [on, setOn] = React.useState(false);
  const [tab, setTab] = React.useState("a");
```

(c) Insert these `<Section>` blocks just before the final closing `</div>` of the returned tree:

```tsx
      <Section title="Switch">
        <Switch checked={on} onCheckedChange={setOn} aria-label="demo switch" />
        <Switch checked={false} onCheckedChange={() => {}} disabled aria-label="disabled switch" />
      </Section>

      <Section title="Checkbox">
        <Checkbox aria-label="unchecked" />
        <Checkbox aria-label="checked" defaultChecked />
        <Checkbox aria-label="disabled" disabled />
      </Section>

      <Section title="Badge">
        {(["default", "secondary", "outline", "success", "warning", "danger", "info"] as const).map(
          (variant) => (
            <Badge key={variant} variant={variant}>
              {variant}
            </Badge>
          )
        )}
      </Section>

      <Section title="Tabs">
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList>
            <TabsTrigger value="a">Overview</TabsTrigger>
            <TabsTrigger value="b">Details</TabsTrigger>
          </TabsList>
          <TabsContent value="a">Overview panel</TabsContent>
          <TabsContent value="b">Details panel</TabsContent>
        </Tabs>
      </Section>

      <Section title="Dropdown">
        <DropdownMenu trigger={<Button variant="outline">Open menu</Button>} label="Demo menu">
          <DropdownItem>First action</DropdownItem>
          <DropdownItem>Second action</DropdownItem>
        </DropdownMenu>
      </Section>
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pnpm exec vitest run src/test/componentsGallery.test.tsx`
Expected: PASS (existing tests + the new section test).

- [ ] **Step 5: Type check**

Run: `pnpm exec tsc --noEmit`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/dev/ComponentsGallery.tsx frontend/src/test/componentsGallery.test.tsx
git commit -m "feat(ui): gallery sections for switch/tabs/dropdown/badge/checkbox"
```

---

### Task 5: Docs + full-gate verification (controller-executed)

**Files:**
- Modify: `docs/FRONTEND.md`

> **Controller note:** `docs/FRONTEND.md` is in the user's uncommitted WIP. This task is executed by the controller (not a subagent): stash the WIP for that file, append the docs, commit only the docs change, then restore the WIP (`git stash pop`) — the same approach used in slice 1's docs task.

- [ ] **Step 1: Update the docs**

In `docs/FRONTEND.md`, under the `### Control contract (core primitives)` subsection, append a bullet:

```markdown
- **Rolled out:** the shared `focusRing` and the `--z-*` / `--elevation-*`
  tokens are also applied to `Switch`, `Tabs`, `DropdownMenu`, `Badge`, and
  `Checkbox` (slice 2). `Dialog` adopts them in a later pass.
```

- [ ] **Step 2: Run the FULL gate first-hand**

Run: `pnpm exec tsc --noEmit`
Expected: PASS (0 errors).

Run: `pnpm lint`
Expected: PASS (0 errors; warning count unchanged from the 44 baseline).

Run: `pnpm test`
Expected: PASS — all suites green, including the new `checkbox`, `badge`, `switch`, `tabs`, `dropdownMenu` test files and the extended `componentsGallery` test.

> If any pre-existing test asserts an old class (e.g. `z-50` or `shadow-xl` on a dropdown, or `h-9` on a tablist), update it to the new token class and re-run. Do not weaken a test — update it to the correct expected value.

- [ ] **Step 3: Commit**

```bash
git add docs/FRONTEND.md
git commit -m "docs(frontend): note the contract rollout to interactive primitives"
```

---

## Self-Review

**Spec coverage:**
- checkbox/badge/switch `focusRing` adoption → Task 1. ✓
- tabs focusRing + `--control-h-md` + `--elevation-1` → Task 2. ✓
- dropdown focusRing + `--z-dropdown` + `--elevation-3` (items unchanged) → Task 3. ✓
- gallery extension → Task 4. ✓
- docs + full gate (first-hand) → Task 5. ✓
- Out of scope (dialog, alert variants, non-interactive primitives, new props) → not touched by any task. ✓
- Dropdown z-50→token behavior change → flagged in Global Constraints + Task 3. ✓

**Placeholder scan:** No TBD/TODO; every code/test step has complete code + an explicit run command and expected result. ✓

**Type consistency:**
- `focusRing` imported identically (`@/components/ui/_shared`) in Tasks 1–3. ✓
- Marker assertion `focus-visible:ring-offset-2` matches the `focusRing` constant value stated in Global Constraints. ✓
- Token classes consistent: `h-[var(--control-h-md)]`, `shadow-[var(--elevation-1)]` (Task 2), `z-[var(--z-dropdown)]`, `shadow-[var(--elevation-3)]` (Task 3) — all reference tokens defined in slice 1's `index.css`. ✓
- Badge variant `success` → `text-success` assertion (Task 1) matches the unchanged badge variant map. ✓

No gaps found.
