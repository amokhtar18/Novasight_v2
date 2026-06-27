# Design — Component System Hardening (Slice 1: Core Control Set)

- **Date:** 2026-06-27
- **Status:** Approved (design); pending implementation plan
- **Area:** `frontend/` — design system / UI primitives
- **Golden rules in play:** #4 (thin vertical slices, no gold-plating), #5 (done = tested + typed + documented)

## Summary

NovaSight already ships a mature, dark-first premium design system (Tailwind v4
CSS-first tokens in `frontend/src/index.css`, hand-rolled shadcn-style primitives
in `frontend/src/components/ui/`, ECharts-themed chart palette). This is **not** a
rebrand and **not** a from-scratch rebuild.

This slice **hardens the core control primitives** into a consistent, documented,
zero-layout-shift contract, and stands up the infrastructure (foundational tokens
+ a living gallery + the molecule layer) that later slices will reuse to roll the
contract out to the remaining primitives and the page-level surfaces.

## Problem (audit findings)

Concrete inconsistencies found in the current primitives:

1. **Inconsistent control heights.** `Button` default is `h-10`; `Input` and
   `Select` are `h-9`. A button placed next to an input does not align — visible
   on every form.
2. **Inconsistent variant patterns.** Only `Button` uses `class-variance-authority`
   (CVA) for variants/sizes. `Card`, `Input`, `Select`, `Dialog` are ad-hoc
   `cn()` strings with no variant API and no size scale.
3. **No standardized state matrix.** Loading / invalid / disabled are handled
   differently (or not at all) per component. `Input` has no `aria-invalid` or
   error styling; `Button` has no built-in `loading` state.
4. **Focus rings differ.** `Button` uses `ring-2 + ring-offset-2`; `Input`/`Select`
   use `ring-2` with no offset.
5. **No living showcase.** All primitives sit in one flat `ui/` folder with no
   gallery to view every component × every state, so visual regressions are
   invisible until they reach a page.
6. **Missing foundational tokens.** No control-size scale, focus-ring token,
   elevation/shadow scale, or z-index scale exist; `z-50` is hardcoded in
   `dialog.tsx`.

## Decisions (locked during brainstorming)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Primary goal | Harden the component system | Foundational; benefits every screen via shared contract |
| Structure | **Hybrid** | Keep atoms flat in `ui/` (no import churn across ~144 files); add `molecules/` + `organisms/` for new composites |
| Showcase | **In-app gallery route** | Dev-only `/dev/components`; no heavy new dependency; dogfoods real theme; visual-regression surface |
| First slice | **Core control set** | `Button`, `Input`, `Textarea` (new), `Select`, `Card` + one `Field` molecule |
| Standardization mechanism | **Shared CVA recipes + thin token layer** (Approach A) | Type-safe, no new runtime dep, consistent with existing `Button` |
| Unified control height | **`h-9` (md) default** | Compact, correct for a dense BI tool; `Button` default moves `h-10` → `h-9` to align with inputs |
| Stitch MCP | **Not on slice-1 critical path** | Stitch is a *screen* generator needing `GOOGLE_CLOUD_PROJECT`; wrong tool for primitive hardening. Use `stitch-build:shadcn-ui` / `taste-design` guidance only |

## Scope

### In scope (Slice 1)

**1. Foundational design tokens** — add to `frontend/src/index.css` in both
`:root` and `.dark` (where theme-dependent):

- **Control-size scale:** `--control-h-sm: 2rem`, `--control-h-md: 2.25rem`,
  `--control-h-lg: 2.5rem`. Default = **md**.
- **Focus ring:** `--focus-ring-width`, `--focus-ring-offset` — one source of
  truth so every primitive focuses identically.
- **Elevation scale:** `--elevation-1` … `--elevation-4` as token-driven shadows,
  tuned separately for light vs dark (dark uses softer, lower-alpha shadows).
  Replaces ad-hoc `shadow-sm` / `shadow-2xl`.
- **Z-index scale:** `--z-base`, `--z-dropdown`, `--z-sticky`, `--z-overlay`,
  `--z-modal`, `--z-popover`, `--z-toast`. Replaces hardcoded `z-50`.

Where Tailwind v4 utilities are needed, expose the tokens through the existing
`@theme inline` mapping block so utilities are generated from them.

**2. Primitive contract** for `Button`, `Input`, `Textarea` (new), `Select`,
`Card`:

- `size`: `sm | md | lg` reading the control-size tokens (default `md`).
- `variant`: per-component, **additive only** — every existing variant preserved
  (e.g. all current `Button` variants keep working).
- **State props:** `invalid` (→ `aria-invalid` + destructive ring), `disabled`,
  and `loading` on `Button` (spinner + `aria-busy`, **width preserved → zero
  layout shift**).
- Unified focus ring applied identically via the new token.
- **No existing prop renamed or removed** — all ~144 consumers keep compiling
  unchanged. `Textarea` is new (additive).

**3. `Field` molecule** — `frontend/src/components/molecules/Field.tsx`:

- Composes `Label` + control + optional hint + error message.
- Auto-wires `htmlFor` / control `id` / `aria-describedby` / `aria-invalid`.
- Generates a stable id (React `useId`) when none is supplied.
- This is where label/error a11y stops being hand-wired per page.

**4. Hybrid folders** — create `frontend/src/components/molecules/` and
`frontend/src/components/organisms/`. Slice 1 populates only `molecules/Field.tsx`;
`organisms/` is created for later slices (may hold a `.gitkeep` until used).

**5. `/dev/components` gallery route**:

- Lazy-loaded page rendering every slice-1 component × every state
  (default / hover / focus / invalid / disabled / loading) × every size, in the
  live app theme, with a light/dark toggle.
- Guarded so it is **dev-only**: the route is registered only when
  `import.meta.env.DEV` is true, and the page chunk is lazy so it is never bundled
  into the production entry.

### Out of scope (explicitly deferred)

- Rolling the contract out to the remaining primitives (`tabs`, `dialog`,
  `dropdown-menu`, `badge`, `alert`, `switch`, `skeleton`, `spinner`, `separator`,
  `empty-state`).
- Migrating hand-rolled `Dialog` / `Select` to Radix headless primitives
  (Approach B) — revisit only if a11y testing exposes gaps.
- Redesigning page-level surfaces (chart builder, SQL/Explore editor, dashboard
  canvas).
- **Stitch screen generation** and any `GOOGLE_CLOUD_PROJECT` setup.

## Component contracts (interfaces)

Each unit has one clear purpose, a typed prop interface, and is independently
testable.

- **`Button`** — adds `loading?: boolean`; existing `variant` + `size` preserved,
  `size` values map to control-size tokens; default height becomes `h-9`. Loading
  shows a spinner without changing the rendered width.
- **`Input`** — adds `size?: 'sm'|'md'|'lg'` and `invalid?: boolean`; height from
  token; unified focus ring; sets `aria-invalid` when `invalid`.
- **`Textarea`** *(new)* — same `invalid` + focus-ring contract; sane default
  `rows`; vertical resize only.
- **`Select`** — adds `size` + `invalid`; keeps the native `<select>` +
  chevron approach (no popup dependency); unified focus ring.
- **`Card`** — adds an `elevation` prop mapping to the elevation tokens; default
  preserves current appearance; sub-components (`CardHeader`/`Title`/…) unchanged.
- **`Field`** *(new molecule)* — props: `label`, `hint?`, `error?`, `htmlFor?`,
  `required?`, `children` (the control). Renders label + control + hint/error and
  wires ARIA.

## Data flow / behavior

These are presentational primitives — no app data flow changes. The only
cross-cutting behavior is ARIA wiring inside `Field` and the `aria-invalid` /
`aria-busy` attributes on controls. The gallery route consumes the components
directly with local state only.

## Error handling / edge cases

- `Field` with no `htmlFor` → generate a stable id via `useId` and link
  label/control/error.
- `Button loading` while `disabled` → remains non-interactive; spinner shown.
- `invalid` + `disabled` together → disabled styling wins for affordance; still
  exposes `aria-invalid`.
- Long content in controls must not break alignment (heights are fixed by token,
  not content).

## Testing strategy (Vitest + RTL)

- Per primitive: renders each `variant` × `size`; `invalid` sets `aria-invalid`;
  `disabled` blocks interaction; `Button loading` shows spinner + `aria-busy` and
  does not change width.
- `Field`: label is associated with control (`htmlFor`/`id`); `error` is linked
  via `aria-describedby` and sets `aria-invalid`; `useId` fallback works with no
  explicit id.
- Keyboard/focus: each control is focusable and shows the focus ring class.

## Definition of done (golden rule #5)

- Vitest/RTL coverage for every slice-1 component state + `Field` a11y wiring.
- `pnpm exec tsc --noEmit` and `pnpm lint` clean.
- a11y baseline: keyboard-reachable, visible focus, correct ARIA on all slice-1
  components (this is the "simulated a11y audit", run as real assertions).
- `docs/FRONTEND.md` design-system section updated; gallery route documented.
- No breaking changes to existing primitive prop APIs (verified by the existing
  ~144 consumers still type-checking).

## Risks / mitigations

- **Visible ripple — Button default `h-10` → `h-9`.** Approved. Improves
  button/input alignment app-wide; prop APIs unchanged (only default visual
  height). Mitigation: it's a token-driven, uniform change; gallery makes it
  visible before merge.
- **Token names colliding with Tailwind v4 generated utilities.** Mitigation:
  namespace custom tokens (`--control-h-*`, `--elevation-*`, `--z-*`) and route
  them through the existing `@theme inline` block deliberately.
- **Gallery accidentally shipping to prod.** Mitigation: `import.meta.env.DEV`
  route guard + lazy chunk; assert in build that the chunk is dev-only.

## Follow-on slices (not now)

1. Roll the contract out to the remaining `ui/` primitives.
2. `organisms/` composites (e.g. Toolbar, DataPanel) as page redesigns need them.
3. Optional Radix migration for `Dialog`/`Select` if a11y gaps surface.
4. Page-level "wow" redesigns (chart builder / Explore / dashboard canvas),
   where Stitch screen generation may be introduced.
