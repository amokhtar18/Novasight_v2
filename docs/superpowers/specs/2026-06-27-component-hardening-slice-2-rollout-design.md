# Design — Component Hardening Slice 2: Contract Rollout to Interactive Primitives

- **Date:** 2026-06-27
- **Status:** Approved (design); pending implementation plan
- **Area:** `frontend/` — design system / UI primitives
- **Predecessor:** Slice 1 ([2026-06-27-component-system-hardening-design.md](2026-06-27-component-system-hardening-design.md)), which created the shared `focusRing` constant and the control-size / focus / elevation / z-index tokens.
- **Golden rules in play:** #4 (thin slice, no gold-plating), #5 (tested + typed + documented).

## Summary

Slice 1 hardened the core control set (Button, Input, Textarea, Select, Card)
and introduced a shared contract: a single `focusRing` class in
`frontend/src/components/ui/_shared.ts` and design tokens
(`--control-h-*`, `--focus-ring*`, `--elevation-*`, `--z-*`) in
`frontend/src/index.css`.

This slice **rolls that contract out to the remaining interactive/overlay
primitives** so the whole system shares one focus ring and one stacking/elevation
scale. It is a mostly behavior-preserving consistency pass — no new props, no new
tokens.

## Problem (audit findings)

Interactive primitives still use ad-hoc inline focus rings and hardcoded
z-index/shadow values instead of the shared contract:

- `checkbox.tsx:18` — inline `focus-visible:ring-2 focus-visible:ring-ring` (no offset).
- `badge.tsx:6` — inline `focus:outline-none focus-visible:ring-2 focus-visible:ring-ring` (no offset).
- `switch.tsx:30` — inline focus ring (has the offset, but duplicated, not shared).
- `tabs.tsx:67` — `TabsTrigger` inline focus ring (no offset); `TabsList` `h-9`
  hardcoded; active trigger uses `shadow-sm`.
- `dropdown-menu.tsx:53,61` — trigger inline focus ring (no offset); panel uses
  hardcoded `z-50` and `shadow-xl`.

Result: focus rings differ subtly across controls, and the new `--z-*` /
`--elevation-*` tokens are defined but unused by the overlay primitives.

## Decisions (locked during brainstorming)

| Decision | Choice |
|----------|--------|
| Scope | **Pure consistency rollout** — adopt `focusRing` + z-index/elevation tokens; no new props/variants (YAGNI) |
| Primitives in scope | `switch`, `tabs`, `dropdown-menu`, `badge`, `checkbox` |
| `dialog.tsx` | **Excluded** — currently in the user's uncommitted WIP; touching it would collide. Fast-follow once that lands. |
| Alert semantic variants (success/warning/info) | **Excluded** — YAGNI; nothing uses them yet |
| Non-interactive primitives (alert/skeleton/separator/spinner/empty-state/label) | **Excluded** — no focus/overlay concern |
| Dropdown menu items | Keep their `bg-accent` focus highlight (correct for `role=menuitem`); do NOT force a ring |
| Gallery | Extend `/dev/components` with sections for the rolled-out primitives |

## Scope — exact changes

All changes reuse existing tokens/constants from slice 1; **no new tokens**.

1. **`checkbox.tsx`** — replace the inline `focus-visible:*` classes with the
   shared `focusRing` (import from `@/components/ui/_shared`). No other change.
2. **`badge.tsx`** — replace the inline focus classes with `focusRing` in the CVA
   base string; all 7 variants unchanged.
3. **`switch.tsx`** — replace the inline focus classes with `focusRing`
   (behavior identical — switch already included the ring offset; this dedupes to
   the shared source of truth).
4. **`tabs.tsx`** —
   - `TabsTrigger`: inline focus classes → `focusRing`.
   - `TabsList`: `h-9` → `h-[var(--control-h-md)]` (token-driven, same height).
   - Active `TabsTrigger`: `shadow-sm` → `shadow-[var(--elevation-1)]`.
5. **`dropdown-menu.tsx`** —
   - Trigger: inline focus classes → `focusRing`.
   - Panel: `z-50` → `z-[var(--z-dropdown)]`; `shadow-xl` → `shadow-[var(--elevation-3)]`.
   - `DropdownItem`/`DropdownLabel`/`DropdownSeparator`: unchanged (item focus
     highlight via `bg-accent` is correct for menuitems).

### Behavior change to note

The dropdown panel's stacking moves from `z-50` (50) to `--z-dropdown` (1000).
Intended: establishes correct ordering under a future modal (`--z-modal` 1300)
and toasts (`--z-toast` 1500). No current consumer pins `z-50`.

### Gallery

Extend `frontend/src/pages/dev/ComponentsGallery.tsx` with sections rendering
`Switch`, `Tabs`, `DropdownMenu`, `Badge`, `Checkbox` across their states
(default/focus/disabled; badge variants; tabs active/inactive; dropdown open).

## Out of scope

- `dialog.tsx` (user WIP).
- Alert semantic-variant expansion.
- Non-interactive primitives (no hardening needed).
- Any new props, sizes, or variants on the in-scope primitives.

## Testing strategy (Vitest + RTL)

- **Focus ring adoption:** assert each rolled-out interactive primitive renders
  with a `focusRing`-specific class that the old inline version lacked — e.g.
  `toHaveClass("focus-visible:ring-offset-2")` for checkbox/badge/tabs-trigger/
  dropdown-trigger (these previously had no offset). For switch, the same
  assertion confirms the shared ring is applied.
- **Tabs tokens:** `TabsList` has `h-[var(--control-h-md)]`; active `TabsTrigger`
  has `shadow-[var(--elevation-1)]`.
- **Dropdown tokens:** the open panel has `z-[var(--z-dropdown)]` and
  `shadow-[var(--elevation-3)]`.
- Preserve existing tests for these primitives (extend, don't weaken).

## Definition of done (golden rule #5)

- Vitest/RTL coverage for the focus/token assertions above.
- `pnpm exec tsc --noEmit` and `pnpm lint` clean (no new warnings).
- Full `pnpm test` green, run first-hand.
- `docs/FRONTEND.md` control-contract section notes the rolled-out primitives.
- No public API change to any primitive (verified by existing consumers still
  compiling).

## Follow-on (not now)

- `dialog.tsx` hardening (z-index → `--z-modal`/`--z-overlay`, shadow →
  `--elevation-4`, close-button `focusRing`) once the user's WIP lands.
- `organisms/` composites and page-level redesigns (later slices).
