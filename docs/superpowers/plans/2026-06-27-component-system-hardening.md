# Component System Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden NovaSight's core UI control primitives into one consistent, tokenized, zero-layout-shift contract, proven by a dev-only component gallery.

**Architecture:** Extend the existing `class-variance-authority` (CVA) pattern (already used by `Button`) to `Input`, `Textarea` (new), `Select`, and `Card`, backed by a small set of new design tokens (control-size scale, elevation, z-index) in `index.css` and a shared TS module of control constants. Add a `Field` molecule that auto-wires label/error ARIA, and a lazy, dev-only `/dev/components` gallery rendering every component × every state. All prop changes are additive — no existing primitive prop is renamed or removed, so the ~144 existing consumers keep compiling unchanged.

**Tech Stack:** React 19, TypeScript, Vite 8, Tailwind CSS v4 (CSS-first `@theme`), class-variance-authority, lucide-react, Vitest + Testing Library, react-router-dom v7.

## Global Constraints

- **Golden rule #4:** thin vertical slice — only the core control set (Button, Input, Textarea, Select, Card, Field). Do NOT touch other primitives (tabs, dialog, dropdown-menu, badge, alert, switch, skeleton, spinner internals, separator, empty-state).
- **Golden rule #5:** done = tested + typed + documented. Final gate must pass `pnpm exec tsc --noEmit` **and** `pnpm lint` **and** `pnpm test` — run the **whole** gate first-hand, not just focused tests.
- **Additive only:** no existing primitive prop may be renamed or removed. New props: `loading` (Button), `size`/`invalid` (Input/Select), `invalid` (Textarea), `elevation` (Card).
- **Unified control height:** default control height is **`--control-h-md` (h-9, 2.25rem)**. Button's default size moves from `h-10` → `h-9`. This is an approved, intended app-wide visual change.
- **Dark-first:** every token added in `:root` must have its dark counterpart in `.dark` **only where theme-dependent** (elevation shadows are; heights / z-index / focus ring are not).
- **No new runtime dependencies.** Use only what's already in `frontend/package.json`.
- **Gallery is dev-only:** never bundled into the production entry (`import.meta.env.DEV` guard + lazy chunk).
- **Imports:** use the `@/` alias and `cn` from `@/lib/cn`, matching existing files.
- **Commit** after each task. Run all commands from the `frontend/` directory.

---

### Task 1: Foundational tokens + shared control constants

**Files:**
- Modify: `frontend/src/index.css` (add tokens to `:root` and `.dark`)
- Create: `frontend/src/components/ui/_shared.ts`
- Test: `frontend/src/test/uiShared.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - CSS tokens: `--control-h-sm|md|lg`, `--focus-ring`, `--focus-ring-offset`, `--elevation-1|2|3|4`, `--z-base|dropdown|sticky|overlay|modal|popover|toast`.
  - `export const controlHeight: { sm: string; md: string; lg: string }` — Tailwind height classes (`"h-[var(--control-h-sm)]"` etc.).
  - `export const focusRing: string` — shared focus-visible ring classes.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/test/uiShared.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { controlHeight, focusRing } from "@/components/ui/_shared";

describe("ui shared control constants", () => {
  it("exposes a sm/md/lg control-height scale bound to the tokens", () => {
    expect(controlHeight.sm).toBe("h-[var(--control-h-sm)]");
    expect(controlHeight.md).toBe("h-[var(--control-h-md)]");
    expect(controlHeight.lg).toBe("h-[var(--control-h-lg)]");
  });

  it("exposes a single focus-ring class string used by every control", () => {
    expect(focusRing).toContain("focus-visible:ring-2");
    expect(focusRing).toContain("focus-visible:ring-ring");
    expect(focusRing).toContain("focus-visible:ring-offset-2");
    expect(focusRing).toContain("outline-none");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm exec vitest run src/test/uiShared.test.ts`
Expected: FAIL — cannot resolve module `@/components/ui/_shared`.

- [ ] **Step 3: Create the shared constants module**

Create `frontend/src/components/ui/_shared.ts`:

```ts
/**
 * Shared control primitives contract.
 *
 * `controlHeight` binds the sm/md/lg control-size tokens (defined in index.css)
 * to Tailwind height classes, so Button/Input/Select/Textarea share one height
 * scale. `focusRing` is the single source of truth for the focus-visible ring,
 * so every interactive control focuses identically.
 */

/** Control-height scale, driven by the --control-h-* tokens in index.css. */
export const controlHeight = {
  sm: "h-[var(--control-h-sm)]",
  md: "h-[var(--control-h-md)]",
  lg: "h-[var(--control-h-lg)]",
} as const;

/** Unified focus-visible ring shared by every interactive control. */
export const focusRing =
  "outline-none ring-offset-background focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";
```

- [ ] **Step 4: Add the design tokens to index.css**

In `frontend/src/index.css`, inside the `:root` block (after `--radius: 0.6rem;`), add:

```css
    /* Control-size scale (not theme-dependent). */
    --control-h-sm: 2rem;
    --control-h-md: 2.25rem;
    --control-h-lg: 2.5rem;

    /* Focus ring (canonical values; applied via the shared focusRing class). */
    --focus-ring: 2px;
    --focus-ring-offset: 2px;

    /* Z-index scale — single source of stacking truth. */
    --z-base: 0;
    --z-dropdown: 1000;
    --z-sticky: 1100;
    --z-overlay: 1200;
    --z-modal: 1300;
    --z-popover: 1400;
    --z-toast: 1500;

    /* Elevation — light theme (crisp, low-alpha slate shadows). */
    --elevation-1: 0 1px 2px 0 hsl(222 47% 11% / 0.06);
    --elevation-2: 0 2px 6px -1px hsl(222 47% 11% / 0.10),
      0 1px 2px -1px hsl(222 47% 11% / 0.06);
    --elevation-3: 0 8px 24px -6px hsl(222 47% 11% / 0.14);
    --elevation-4: 0 16px 48px -12px hsl(222 47% 11% / 0.22);
```

In the `.dark` block (after `--ring: 256 90% 68%;`), add the dark elevation overrides (softer, near-black, higher blur):

```css
    /* Elevation — dark theme (deeper, softer, near-black shadows). */
    --elevation-1: 0 1px 2px 0 hsl(224 60% 2% / 0.40);
    --elevation-2: 0 2px 8px -1px hsl(224 60% 2% / 0.50);
    --elevation-3: 0 10px 30px -8px hsl(224 60% 2% / 0.60);
    --elevation-4: 0 20px 60px -16px hsl(224 60% 2% / 0.70);
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pnpm exec vitest run src/test/uiShared.test.ts`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add src/components/ui/_shared.ts src/test/uiShared.test.ts src/index.css
git commit -m "feat(ui): foundational control tokens + shared control constants"
```

---

### Task 2: Button — loading state, tokenized sizes, shared focus ring

**Files:**
- Modify: `frontend/src/components/ui/button.tsx`
- Test: `frontend/src/test/button.test.tsx`

**Interfaces:**
- Consumes: `controlHeight`, `focusRing` from `@/components/ui/_shared`; `Spinner` from `@/components/ui/spinner`.
- Produces: `Button` with new optional props `loading?: boolean` and `loadingLabel?: string`; `size` keeps `default | sm | lg | icon` and adds `md` (alias of `default`, both = h-9). `buttonVariants` export retained.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/test/button.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { Button } from "@/components/ui/button";

describe("Button", () => {
  it("renders a md (h-9) default height", () => {
    render(<Button>Save</Button>);
    expect(screen.getByRole("button", { name: "Save" })).toHaveClass(
      "h-[var(--control-h-md)]"
    );
  });

  it("shows a spinner, marks aria-busy, and disables while loading", () => {
    render(<Button loading>Save</Button>);
    const button = screen.getByRole("button", { name: /save/i });
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(button).toBeDisabled();
    // role=status comes from <Spinner> — proves the spinner is rendered.
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("keeps its label in the DOM while loading (width preserved, zero shift)", () => {
    render(<Button loading>Save</Button>);
    expect(screen.getByText("Save")).toBeInTheDocument();
  });

  it("does not fire onClick while loading", async () => {
    let clicks = 0;
    const user = userEvent.setup();
    render(
      <Button loading onClick={() => (clicks += 1)}>
        Save
      </Button>
    );
    await user.click(screen.getByRole("button"));
    expect(clicks).toBe(0);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm exec vitest run src/test/button.test.tsx`
Expected: FAIL — no `h-[var(--control-h-md)]` class and no `aria-busy`/spinner (current Button is `h-10`, has no `loading`).

- [ ] **Step 3: Rewrite button.tsx**

Replace the full contents of `frontend/src/components/ui/button.tsx`:

```tsx
import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/cn";
import { Spinner } from "@/components/ui/spinner";
import { controlHeight, focusRing } from "@/components/ui/_shared";

const buttonVariants = cva(
  [
    focusRing,
    "relative inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors disabled:pointer-events-none disabled:opacity-50",
  ],
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:bg-primary/90",
        destructive:
          "bg-destructive text-destructive-foreground hover:bg-destructive/90",
        outline:
          "border border-input bg-background hover:bg-accent hover:text-accent-foreground",
        secondary:
          "bg-secondary text-secondary-foreground hover:bg-secondary/80",
        ghost: "hover:bg-accent hover:text-accent-foreground",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        // `default` retained for backward compat; now h-9 to align with inputs.
        default: cn(controlHeight.md, "px-4"),
        md: cn(controlHeight.md, "px-4"),
        sm: cn(controlHeight.sm, "rounded-md px-3"),
        lg: cn(controlHeight.lg, "rounded-md px-6"),
        icon: cn(controlHeight.md, "w-[var(--control-h-md)]"),
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  /** Show a spinner, set aria-busy, and disable the button. Zero layout shift. */
  loading?: boolean;
  /** Accessible label for the loading spinner. */
  loadingLabel?: string;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      className,
      variant,
      size,
      asChild = false,
      loading = false,
      loadingLabel = "Loading",
      disabled,
      children,
      ...props
    },
    ref
  ) => {
    // asChild renders a single arbitrary child (e.g. <Link>) via Slot; the
    // loading affordance only applies to the real <button> path.
    if (asChild) {
      return (
        <Slot
          className={cn(buttonVariants({ variant, size, className }))}
          ref={ref}
          {...props}
        >
          {children}
        </Slot>
      );
    }
    return (
      <button
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        disabled={disabled || loading}
        aria-busy={loading || undefined}
        {...props}
      >
        {loading && (
          <span className="absolute inset-0 grid place-items-center">
            <Spinner label={loadingLabel} className="text-current" />
          </span>
        )}
        <span className={cn("inline-flex items-center gap-2", loading && "invisible")}>
          {children}
        </span>
      </button>
    );
  }
);
Button.displayName = "Button";

export { Button, buttonVariants };
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm exec vitest run src/test/button.test.tsx`
Expected: PASS (4 tests).

- [ ] **Step 5: Guard against regressions in existing consumers**

Run: `pnpm exec tsc --noEmit`
Expected: PASS — no consumer broke (all existing `size`/`variant` values still exist; new props are optional).

- [ ] **Step 6: Commit**

```bash
git add src/components/ui/button.tsx src/test/button.test.tsx
git commit -m "feat(ui): Button loading state + tokenized sizes (h-9 default)"
```

---

### Task 3: Input — CVA size, invalid state, shared focus ring

**Files:**
- Modify: `frontend/src/components/ui/input.tsx`
- Test: `frontend/src/test/input.test.tsx`

**Interfaces:**
- Consumes: `controlHeight`, `focusRing` from `@/components/ui/_shared`.
- Produces: `Input` with `size?: "sm" | "md" | "lg"` (default `md`, native numeric `size` omitted) and `invalid?: boolean`. Type `InputProps` retained.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/test/input.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { Input } from "@/components/ui/input";

describe("Input", () => {
  it("defaults to the md (h-9) control height", () => {
    render(<Input aria-label="name" />);
    expect(screen.getByLabelText("name")).toHaveClass("h-[var(--control-h-md)]");
  });

  it("applies the sm height when size=sm", () => {
    render(<Input aria-label="name" size="sm" />);
    expect(screen.getByLabelText("name")).toHaveClass("h-[var(--control-h-sm)]");
  });

  it("sets aria-invalid when invalid", () => {
    render(<Input aria-label="name" invalid />);
    expect(screen.getByLabelText("name")).toHaveAttribute("aria-invalid", "true");
  });

  it("is not aria-invalid by default", () => {
    render(<Input aria-label="name" />);
    expect(screen.getByLabelText("name")).not.toHaveAttribute("aria-invalid");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm exec vitest run src/test/input.test.tsx`
Expected: FAIL — current Input is `h-9` literal (no token class) and has no `invalid`.

- [ ] **Step 3: Rewrite input.tsx**

Replace the full contents of `frontend/src/components/ui/input.tsx`:

```tsx
import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/cn";
import { controlHeight, focusRing } from "@/components/ui/_shared";

const inputVariants = cva(
  cn(
    "flex w-full rounded-md border border-input bg-background/60 text-sm shadow-sm transition-colors",
    "placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50",
    focusRing
  ),
  {
    variants: {
      size: {
        sm: cn(controlHeight.sm, "px-2.5 py-1"),
        md: cn(controlHeight.md, "px-3 py-1"),
        lg: cn(controlHeight.lg, "px-3.5 py-2"),
      },
    },
    defaultVariants: { size: "md" },
  }
);

export interface InputProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "size">,
    VariantProps<typeof inputVariants> {
  /** Mark the field invalid: sets aria-invalid and a destructive ring. */
  invalid?: boolean;
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type = "text", size, invalid, ...props }, ref) => (
    <input
      ref={ref}
      type={type}
      aria-invalid={invalid ? true : undefined}
      className={cn(
        inputVariants({ size }),
        invalid && "border-destructive focus-visible:ring-destructive",
        className
      )}
      {...props}
    />
  )
);
Input.displayName = "Input";
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm exec vitest run src/test/input.test.tsx`
Expected: PASS (4 tests).

- [ ] **Step 5: Guard against regressions**

Run: `pnpm exec tsc --noEmit`
Expected: PASS — no consumer passes a native numeric `size` to `Input` (verified), so omitting it is safe.

- [ ] **Step 6: Commit**

```bash
git add src/components/ui/input.tsx src/test/input.test.tsx
git commit -m "feat(ui): Input size scale + invalid state + shared focus ring"
```

---

### Task 4: Textarea (new primitive)

**Files:**
- Create: `frontend/src/components/ui/textarea.tsx`
- Test: `frontend/src/test/textarea.test.tsx`

**Interfaces:**
- Consumes: `focusRing` from `@/components/ui/_shared`.
- Produces: `Textarea` (forwardRef to `HTMLTextAreaElement`) with `invalid?: boolean`; default `rows={4}`, vertical resize only. Type `TextareaProps` exported.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/test/textarea.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { Textarea } from "@/components/ui/textarea";

describe("Textarea", () => {
  it("renders with a sane default row count", () => {
    render(<Textarea aria-label="notes" />);
    expect(screen.getByLabelText("notes")).toHaveAttribute("rows", "4");
  });

  it("sets aria-invalid when invalid", () => {
    render(<Textarea aria-label="notes" invalid />);
    expect(screen.getByLabelText("notes")).toHaveAttribute("aria-invalid", "true");
  });

  it("accepts typed input", async () => {
    const user = userEvent.setup();
    render(<Textarea aria-label="notes" />);
    const el = screen.getByLabelText<HTMLTextAreaElement>("notes");
    await user.type(el, "hello");
    expect(el).toHaveValue("hello");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm exec vitest run src/test/textarea.test.tsx`
Expected: FAIL — cannot resolve `@/components/ui/textarea`.

- [ ] **Step 3: Create textarea.tsx**

Create `frontend/src/components/ui/textarea.tsx`:

```tsx
import * as React from "react";
import { cva } from "class-variance-authority";
import { cn } from "@/lib/cn";
import { focusRing } from "@/components/ui/_shared";

const textareaVariants = cva(
  cn(
    "flex w-full resize-y rounded-md border border-input bg-background/60 px-3 py-2 text-sm shadow-sm transition-colors",
    "placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50",
    focusRing
  )
);

export interface TextareaProps
  extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  /** Mark the field invalid: sets aria-invalid and a destructive ring. */
  invalid?: boolean;
}

export const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, invalid, rows = 4, ...props }, ref) => (
    <textarea
      ref={ref}
      rows={rows}
      aria-invalid={invalid ? true : undefined}
      className={cn(
        textareaVariants(),
        invalid && "border-destructive focus-visible:ring-destructive",
        className
      )}
      {...props}
    />
  )
);
Textarea.displayName = "Textarea";
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm exec vitest run src/test/textarea.test.tsx`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/components/ui/textarea.tsx src/test/textarea.test.tsx
git commit -m "feat(ui): add Textarea primitive (invalid + shared focus ring)"
```

---

### Task 5: Select — CVA size + invalid state

**Files:**
- Modify: `frontend/src/components/ui/select.tsx`
- Test: `frontend/src/test/select.test.tsx`

**Interfaces:**
- Consumes: `controlHeight`, `focusRing` from `@/components/ui/_shared`.
- Produces: `Select` with `size?: "sm" | "md" | "lg"` (default `md`, native numeric `size` omitted) and `invalid?: boolean`; keeps the native `<select>` + chevron. Type `SelectProps` retained.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/test/select.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { Select } from "@/components/ui/select";

function options() {
  return (
    <>
      <option value="a">A</option>
      <option value="b">B</option>
    </>
  );
}

describe("Select", () => {
  it("defaults to the md (h-9) control height", () => {
    render(
      <Select aria-label="pick" defaultValue="a">
        {options()}
      </Select>
    );
    expect(screen.getByLabelText("pick")).toHaveClass("h-[var(--control-h-md)]");
  });

  it("sets aria-invalid when invalid", () => {
    render(
      <Select aria-label="pick" invalid defaultValue="a">
        {options()}
      </Select>
    );
    expect(screen.getByLabelText("pick")).toHaveAttribute("aria-invalid", "true");
  });

  it("renders its options", () => {
    render(
      <Select aria-label="pick" defaultValue="a">
        {options()}
      </Select>
    );
    expect(screen.getByRole("option", { name: "A" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "B" })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm exec vitest run src/test/select.test.tsx`
Expected: FAIL — current Select is `h-9` literal and has no `invalid`.

- [ ] **Step 3: Rewrite select.tsx**

Replace the full contents of `frontend/src/components/ui/select.tsx`:

```tsx
import * as React from "react";
import { ChevronsUpDown } from "lucide-react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/cn";
import { controlHeight, focusRing } from "@/components/ui/_shared";

const selectVariants = cva(
  cn(
    "w-full appearance-none rounded-md border border-input bg-background/60 pr-8 text-sm shadow-sm transition-colors",
    "disabled:cursor-not-allowed disabled:opacity-50",
    focusRing
  ),
  {
    variants: {
      size: {
        sm: cn(controlHeight.sm, "pl-2.5"),
        md: cn(controlHeight.md, "pl-3"),
        lg: cn(controlHeight.lg, "pl-3.5"),
      },
    },
    defaultVariants: { size: "md" },
  }
);

export interface SelectProps
  extends Omit<React.SelectHTMLAttributes<HTMLSelectElement>, "size">,
    VariantProps<typeof selectVariants> {
  /** Mark the field invalid: sets aria-invalid and a destructive ring. */
  invalid?: boolean;
}

/**
 * Styled native <select> — accessible by default and keyboard friendly, without
 * pulling in a popup-menu dependency. Wrap <option> children as usual.
 */
export const Select = React.forwardRef<HTMLSelectElement, SelectProps>(
  ({ className, size, invalid, children, ...props }, ref) => (
    <div className="relative">
      <select
        ref={ref}
        aria-invalid={invalid ? true : undefined}
        className={cn(
          selectVariants({ size }),
          invalid && "border-destructive focus-visible:ring-destructive",
          className
        )}
        {...props}
      >
        {children}
      </select>
      <ChevronsUpDown
        className="pointer-events-none absolute right-2 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
        aria-hidden
      />
    </div>
  )
);
Select.displayName = "Select";
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm exec vitest run src/test/select.test.tsx`
Expected: PASS (3 tests).

- [ ] **Step 5: Guard against regressions**

Run: `pnpm exec tsc --noEmit`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/components/ui/select.tsx src/test/select.test.tsx
git commit -m "feat(ui): Select size scale + invalid state"
```

---

### Task 6: Card — elevation prop

**Files:**
- Modify: `frontend/src/components/ui/card.tsx`
- Test: `frontend/src/test/card.test.tsx`

**Interfaces:**
- Consumes: nothing new (uses elevation tokens via arbitrary classes).
- Produces: `Card` with `elevation?: "none" | "sm" | "md" | "lg"` (default `sm`, maps to `--elevation-1`). All `Card*` sub-components unchanged.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/test/card.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { Card } from "@/components/ui/card";

describe("Card", () => {
  it("defaults to elevation 1 (sm)", () => {
    render(<Card data-testid="card">body</Card>);
    expect(screen.getByTestId("card")).toHaveClass("shadow-[var(--elevation-1)]");
  });

  it("applies a higher elevation when requested", () => {
    render(
      <Card data-testid="card" elevation="lg">
        body
      </Card>
    );
    expect(screen.getByTestId("card")).toHaveClass("shadow-[var(--elevation-3)]");
  });

  it("renders no shadow when elevation=none", () => {
    render(
      <Card data-testid="card" elevation="none">
        body
      </Card>
    );
    const el = screen.getByTestId("card");
    expect(el).not.toHaveClass("shadow-[var(--elevation-1)]");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm exec vitest run src/test/card.test.tsx`
Expected: FAIL — current Card uses `shadow-sm` and has no `elevation` prop.

- [ ] **Step 3: Modify card.tsx (Card component only)**

In `frontend/src/components/ui/card.tsx`, replace the import line and the `Card` definition (leave `CardHeader`/`CardTitle`/`CardDescription`/`CardContent`/`CardFooter` and the `export` block unchanged).

Replace:

```tsx
import * as React from "react";
import { cn } from "@/lib/cn";

const Card = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn(
      "rounded-lg border bg-card text-card-foreground shadow-sm",
      className
    )}
    {...props}
  />
));
Card.displayName = "Card";
```

with:

```tsx
import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/cn";

const cardVariants = cva("rounded-lg border bg-card text-card-foreground", {
  variants: {
    elevation: {
      none: "",
      sm: "shadow-[var(--elevation-1)]",
      md: "shadow-[var(--elevation-2)]",
      lg: "shadow-[var(--elevation-3)]",
    },
  },
  defaultVariants: { elevation: "sm" },
});

export interface CardProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof cardVariants> {}

const Card = React.forwardRef<HTMLDivElement, CardProps>(
  ({ className, elevation, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(cardVariants({ elevation }), className)}
      {...props}
    />
  )
);
Card.displayName = "Card";
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm exec vitest run src/test/card.test.tsx`
Expected: PASS (3 tests).

- [ ] **Step 5: Guard against regressions**

Run: `pnpm exec tsc --noEmit`
Expected: PASS — `elevation` is optional; existing `<Card>` usages are unaffected.

- [ ] **Step 6: Commit**

```bash
git add src/components/ui/card.tsx src/test/card.test.tsx
git commit -m "feat(ui): Card elevation prop bound to elevation tokens"
```

---

### Task 7: Field molecule (+ organisms folder)

**Files:**
- Create: `frontend/src/components/molecules/Field.tsx`
- Create: `frontend/src/components/organisms/.gitkeep`
- Test: `frontend/src/test/field.test.tsx`

**Interfaces:**
- Consumes: `Label` from `@/components/ui/label`; `cn` from `@/lib/cn`.
- Produces: `Field` — props `{ label: string; htmlFor?: string; hint?: string; error?: string; required?: boolean; className?: string; children: React.ReactElement }`. Clones the single control child to inject `id`, `aria-invalid`, `aria-describedby`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/test/field.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { Field } from "@/components/molecules/Field";
import { Input } from "@/components/ui/input";

describe("Field", () => {
  it("associates the label with the control", () => {
    render(
      <Field label="Email">
        <Input />
      </Field>
    );
    // getByLabelText resolves the control via the generated htmlFor/id link.
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
  });

  it("links an error message and marks the control invalid", () => {
    render(
      <Field label="Email" error="Required">
        <Input />
      </Field>
    );
    const input = screen.getByLabelText("Email");
    expect(input).toHaveAttribute("aria-invalid", "true");
    const describedBy = input.getAttribute("aria-describedby");
    expect(describedBy).toBeTruthy();
    expect(screen.getByText("Required").id).toBe(describedBy);
  });

  it("shows the hint when there is no error", () => {
    render(
      <Field label="Email" hint="We never share it">
        <Input />
      </Field>
    );
    expect(screen.getByText("We never share it")).toBeInTheDocument();
  });

  it("hides the hint when an error is present", () => {
    render(
      <Field label="Email" hint="We never share it" error="Required">
        <Input />
      </Field>
    );
    expect(screen.queryByText("We never share it")).not.toBeInTheDocument();
    expect(screen.getByText("Required")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm exec vitest run src/test/field.test.tsx`
Expected: FAIL — cannot resolve `@/components/molecules/Field`.

- [ ] **Step 3: Create the organisms placeholder + Field**

Create `frontend/src/components/organisms/.gitkeep` (empty file — reserves the layer for later slices).

Create `frontend/src/components/molecules/Field.tsx`:

```tsx
import * as React from "react";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/cn";

type ControlChild = React.ReactElement<{
  id?: string;
  "aria-invalid"?: boolean | "true" | "false";
  "aria-describedby"?: string;
}>;

interface FieldProps {
  /** Visible label text. */
  label: string;
  /** Optional explicit id for the control; auto-generated when omitted. */
  htmlFor?: string;
  /** Helper text shown below the control when there is no error. */
  hint?: string;
  /** Error message; when set, links the message and marks the control invalid. */
  error?: string;
  /** Show a required asterisk. */
  required?: boolean;
  className?: string;
  /** The single control element (Input, Select, Textarea, …). */
  children: ControlChild;
}

/**
 * Field — composes Label + control + hint/error and auto-wires the a11y
 * relationships (htmlFor/id, aria-invalid, aria-describedby) so pages stop
 * hand-wiring them. Pass exactly one control as the child.
 */
export function Field({
  label,
  htmlFor,
  hint,
  error,
  required,
  className,
  children,
}: FieldProps) {
  const generatedId = React.useId();
  const controlId = htmlFor ?? children.props.id ?? generatedId;
  const hintId = hint && !error ? `${controlId}-hint` : undefined;
  const errorId = error ? `${controlId}-error` : undefined;
  const describedBy =
    [hintId, errorId].filter(Boolean).join(" ") || undefined;

  const control = React.cloneElement(children, {
    id: controlId,
    "aria-invalid": error ? true : children.props["aria-invalid"],
    "aria-describedby": describedBy ?? children.props["aria-describedby"],
  });

  return (
    <div className={cn("space-y-1.5", className)}>
      <Label htmlFor={controlId}>
        {label}
        {required && (
          <span aria-hidden className="ml-0.5 text-destructive">
            *
          </span>
        )}
      </Label>
      {control}
      {hintId && (
        <p id={hintId} className="text-xs text-muted-foreground">
          {hint}
        </p>
      )}
      {errorId && (
        <p id={errorId} className="text-xs text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm exec vitest run src/test/field.test.tsx`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/components/molecules/Field.tsx src/components/organisms/.gitkeep src/test/field.test.tsx
git commit -m "feat(ui): Field molecule with auto-wired label/error a11y"
```

---

### Task 8: Dev-only /dev/components gallery route

**Files:**
- Create: `frontend/src/pages/dev/ComponentsGallery.tsx`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/test/componentsGallery.test.tsx`

**Interfaces:**
- Consumes: all slice-1 primitives + `Field`.
- Produces: `ComponentsGallery` page component (named export), registered at `/dev/components` only when `import.meta.env.DEV`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/test/componentsGallery.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { ComponentsGallery } from "@/pages/dev/ComponentsGallery";

describe("ComponentsGallery", () => {
  it("renders the component catalog with the primitive sections", () => {
    render(<ComponentsGallery />);
    expect(
      screen.getByRole("heading", { name: /component gallery/i })
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /^button$/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /^field$/i })).toBeInTheDocument();
  });

  it("renders a loading-state button (aria-busy)", () => {
    render(<ComponentsGallery />);
    const busy = screen
      .getAllByRole("button")
      .filter((b) => b.getAttribute("aria-busy") === "true");
    expect(busy.length).toBeGreaterThan(0);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm exec vitest run src/test/componentsGallery.test.tsx`
Expected: FAIL — cannot resolve `@/pages/dev/ComponentsGallery`.

- [ ] **Step 3: Create the gallery page**

Create `frontend/src/pages/dev/ComponentsGallery.tsx`:

```tsx
/**
 * Dev-only component gallery — renders every slice-1 primitive across its
 * variants and states (default/hover/focus/invalid/disabled/loading) in the
 * live app theme. Registered only when import.meta.env.DEV (see App.tsx) and
 * lazy-loaded, so it never ships in the production bundle. It is the visual
 * regression surface for the hardened control contract.
 */

import * as React from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select } from "@/components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Field } from "@/components/molecules/Field";

type Size = "sm" | "md" | "lg";
const SIZES: Size[] = ["sm", "md", "lg"];
const BUTTON_VARIANTS = [
  "default",
  "secondary",
  "outline",
  "ghost",
  "destructive",
  "link",
] as const;

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-4">
      <h2 className="text-xl font-semibold tracking-tight">{title}</h2>
      <Card>
        <CardContent className="flex flex-wrap items-end gap-4 p-6">
          {children}
        </CardContent>
      </Card>
    </section>
  );
}

export function ComponentsGallery() {
  return (
    <div className="mx-auto max-w-5xl space-y-10 py-10">
      <header className="space-y-1">
        <h1 className="text-3xl font-semibold tracking-tight">
          Component Gallery
        </h1>
        <p className="text-muted-foreground">
          Slice 1 — core control set. Toggle the app theme (Settings) to inspect
          light and dark.
        </p>
      </header>

      <Section title="Button">
        <div className="flex flex-wrap items-center gap-3">
          {BUTTON_VARIANTS.map((variant) => (
            <Button key={variant} variant={variant}>
              {variant}
            </Button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {SIZES.map((size) => (
            <Button key={size} size={size}>
              size {size}
            </Button>
          ))}
          <Button disabled>disabled</Button>
          <Button loading>loading</Button>
        </div>
      </Section>

      <Section title="Input">
        {SIZES.map((size) => (
          <Input
            key={size}
            size={size}
            aria-label={`input ${size}`}
            placeholder={`size ${size}`}
          />
        ))}
        <Input aria-label="invalid input" invalid placeholder="invalid" />
        <Input aria-label="disabled input" disabled placeholder="disabled" />
      </Section>

      <Section title="Textarea">
        <Textarea aria-label="textarea" placeholder="Type here…" />
        <Textarea aria-label="invalid textarea" invalid placeholder="invalid" />
      </Section>

      <Section title="Select">
        {SIZES.map((size) => (
          <Select key={size} size={size} aria-label={`select ${size}`} defaultValue="a">
            <option value="a">Option A</option>
            <option value="b">Option B</option>
          </Select>
        ))}
        <Select aria-label="invalid select" invalid defaultValue="a">
          <option value="a">Invalid</option>
        </Select>
      </Section>

      <Section title="Card">
        {(["none", "sm", "md", "lg"] as const).map((elevation) => (
          <Card key={elevation} elevation={elevation} className="w-40">
            <CardHeader>
              <CardTitle className="text-base">elevation {elevation}</CardTitle>
            </CardHeader>
            <CardContent className="text-sm text-muted-foreground">
              Surface
            </CardContent>
          </Card>
        ))}
      </Section>

      <Section title="Field">
        <div className="w-full max-w-sm space-y-4">
          <Field label="Email" hint="We never share it">
            <Input placeholder="you@example.com" />
          </Field>
          <Field label="Name" required error="This field is required">
            <Input defaultValue="" />
          </Field>
          <Field label="Notes">
            <Textarea placeholder="Optional notes" />
          </Field>
        </div>
      </Section>
    </div>
  );
}
```

- [ ] **Step 4: Register the route in App.tsx (dev-only)**

In `frontend/src/App.tsx`, add the lazy declaration after the `Settings` lazy import (around line 56):

```tsx
// Dev-only component gallery. import.meta.env.DEV is statically false in prod
// builds, so this branch (and its dynamic import) is tree-shaken out entirely.
const ComponentsGallery = import.meta.env.DEV
  ? lazy(() =>
      import("@/pages/dev/ComponentsGallery").then((m) => ({
        default: m.ComponentsGallery,
      }))
    )
  : null;
```

Then, inside the `AppShell` route block (after the `settings` route, before the `*` NotFound route), add:

```tsx
          {import.meta.env.DEV && ComponentsGallery && (
            <Route path="dev/components" element={<ComponentsGallery />} />
          )}
```

- [ ] **Step 5: Run test + type check to verify they pass**

Run: `pnpm exec vitest run src/test/componentsGallery.test.tsx`
Expected: PASS (2 tests).

Run: `pnpm exec tsc --noEmit`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/pages/dev/ComponentsGallery.tsx src/App.tsx src/test/componentsGallery.test.tsx
git commit -m "feat(ui): dev-only /dev/components gallery for the core control set"
```

---

### Task 9: Documentation + full-gate verification

**Files:**
- Modify: `docs/FRONTEND.md` (design-system section)

**Interfaces:**
- Consumes: everything above.
- Produces: updated docs; a green full gate.

- [ ] **Step 1: Update the design-system docs**

In `docs/FRONTEND.md`, under `## Design system & theming`, append:

```markdown

### Control contract (core primitives)

The core controls share one contract, backed by tokens in `src/index.css`:

- **Sizes:** `Button`, `Input`, `Select` take `size="sm" | "md" | "lg"` (default
  `md` = `--control-h-md`, 2.25rem / h-9). Heights come from the
  `--control-h-*` tokens via `src/components/ui/_shared.ts` (`controlHeight`), so
  buttons and inputs always align.
- **Focus:** every control uses the shared `focusRing` class (`_shared.ts`) — one
  focus-visible ring everywhere.
- **Invalid:** `Input`, `Select`, `Textarea` accept `invalid` (sets `aria-invalid`
  + a destructive ring).
- **Loading:** `Button` accepts `loading` (spinner overlay + `aria-busy` +
  disabled, with zero layout shift — the label stays laid out).
- **Elevation:** `Card` accepts `elevation="none" | "sm" | "md" | "lg"` (default
  `sm` = `--elevation-1`); shadows are theme-aware.
- **Field molecule:** `src/components/molecules/Field.tsx` composes
  label + control + hint/error and auto-wires `htmlFor`/`id`/`aria-describedby`/
  `aria-invalid`. Pass exactly one control as the child.

New composite layers live in `src/components/molecules/` and
`src/components/organisms/` (atoms stay in `src/components/ui/`).

### Component gallery (dev only)

`/dev/components` renders every core primitive across its variants and states in
the live theme. It is registered only when `import.meta.env.DEV` and lazy-loaded,
so it never ships in production. Use it as the visual-regression surface when
changing a primitive.
```

- [ ] **Step 2: Run the FULL gate first-hand**

Run: `pnpm exec tsc --noEmit`
Expected: PASS (no errors).

Run: `pnpm lint`
Expected: PASS (no errors).

Run: `pnpm test`
Expected: PASS — all suites green, including the 6 new test files
(`uiShared`, `button`, `input`, `textarea`, `select`, `card`, `field`,
`componentsGallery`) and every pre-existing suite.

> If any pre-existing test fails due to the Button `h-10` → `h-9` change or a
> snapshot, fix the assertion to match the new (intended) height and re-run the
> full gate. Do not weaken a test to make it pass — update it to the correct
> expected value.

- [ ] **Step 3: Commit**

```bash
git add docs/FRONTEND.md
git commit -m "docs(frontend): document the hardened control contract + gallery"
```

---

## Self-Review

**Spec coverage:**
- Foundational tokens (control-size, focus-ring, elevation, z-index) → Task 1. ✓
- Primitive contract (Button loading; Input/Select size+invalid; Textarea; Card elevation; unified focus ring; h-9 default; additive-only) → Tasks 2–6. ✓
- Field molecule + Hybrid folders (`molecules/`, `organisms/`) → Task 7. ✓
- `/dev/components` dev-only gallery → Task 8. ✓
- Testing per component + Field a11y wiring → Tasks 2–8. ✓
- Definition of done (tsc + lint + full test suite, run first-hand) + docs → Task 9. ✓
- Out-of-scope items (other primitives, Radix migration, page redesigns, Stitch) → not touched by any task. ✓

**Placeholder scan:** No TBD/TODO; every code/test step contains complete code and an explicit run command + expected result. ✓

**Type consistency:**
- `controlHeight` / `focusRing` defined in Task 1, consumed with identical names in Tasks 2–5. ✓
- Button `size` keeps `default | sm | lg | icon`, adds `md`; gallery uses only `sm | md | lg`. ✓
- Input/Select `Omit<…, "size">` + `size: "sm"|"md"|"lg"` + `invalid` — consistent across Tasks 3/5/8. ✓
- `Field` child clone keys (`id`, `aria-invalid`, `aria-describedby`) match the props the controls accept (Input/Select/Textarea all forward arbitrary attrs). ✓
- `Card` `elevation` values (`none|sm|md|lg`) consistent between Task 6 and the gallery in Task 8. ✓

No gaps found.
