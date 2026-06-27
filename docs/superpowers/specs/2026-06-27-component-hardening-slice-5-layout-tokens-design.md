# Design — Component Hardening Slice 5: Layout z-index / Elevation Tokens

- **Date:** 2026-06-27
- **Status:** Approved (design); pending implementation plan
- **Area:** `frontend/` — layout chrome + overlay components
- **Predecessors:** Slices 1–4 (primitives, contract rollout, page + checkbox adoption). The `--z-*` / `--elevation-*` tokens were created in slice 1 and so far only `DropdownMenu` + `Card` use them.
- **Golden rules in play:** #4 (thin slice), #5 (tested + typed + documented).

## Summary

The app's layout chrome (sticky topbar, mobile sidebar overlay, skip-nav) and its
floating overlays (chart-actions menu, tile-size popover, drag preview) still use
**hardcoded** `z-30`/`z-50`/`z-20` and `shadow-md`/`shadow-2xl`/`shadow-lg`. This
slice maps them to the existing `--z-*` / `--elevation-*` tokens, giving the app a
**single source of truth for stacking and elevation**. Behavior-preserving in
intent (the resulting visual order is the same or corrected).

## Problem (audit findings)

Hardcoded stacking / heavy shadows outside the `ui/` primitives:

| File:line | Hardcoded |
|-----------|-----------|
| `components/layout/TopBar.tsx:45` | `sticky … z-30` |
| `components/layout/Sidebar.tsx:181` | overlay `z-50` |
| `components/layout/Sidebar.tsx:187` | drawer `shadow-2xl` |
| `components/layout/AppShell.tsx:22` | skip-nav `focus:z-50` |
| `components/chart/ChartActionsMenu.tsx:96` | popover `z-30` + `shadow-md` |
| `components/dashboard/TileSizeControl.tsx:76` | popover `z-20` + `shadow-md` |
| `components/chart/SemanticQueryBuilder.tsx:421` | drag preview `shadow-lg` |

These bypass the `--z-*`/`--elevation-*` scale, so the stacking order is implicit
and the tokens are mostly unused.

## Decisions (locked during brainstorming)

| Site | z-index | elevation |
|------|---------|-----------|
| TopBar sticky header | `z-30` → `z-[var(--z-sticky)]` (1100) | — |
| Sidebar mobile overlay | `z-50` → `z-[var(--z-overlay)]` (1200) | — |
| Sidebar mobile drawer | — | `shadow-2xl` → `shadow-[var(--elevation-4)]` |
| AppShell skip-nav | `focus:z-50` → `focus:z-[var(--z-overlay)]` | — |
| ChartActionsMenu popover | `z-30` → `z-[var(--z-dropdown)]` (1000) | `shadow-md` → `shadow-[var(--elevation-2)]` |
| TileSizeControl popover | `z-20` → `z-[var(--z-dropdown)]` | `shadow-md` → `shadow-[var(--elevation-2)]` |
| SemanticQueryBuilder drag preview | — | `shadow-lg` → `shadow-[var(--elevation-3)]` |

**Resulting single global order:** dropdown (1000) < sticky topbar (1100) <
overlay / sidebar / skip-nav (1200) < modal (1300, = future `dialog`) < popover
(1400) < toast (1500).

**Excluded:** `DashboardCardTile.tsx:254` `z-10` (local within-tile stacking, not
a global overlay layer); `dialog.tsx` (user WIP).

## Scope — the swaps

Pure className edits — replace the hardcoded utility with the arbitrary-value
token utility (`z-[var(--z-…)]`, `shadow-[var(--elevation-…)]`). No structural,
prop, or logic changes. No new tokens (all exist in `index.css` from slice 1).

## Out of scope

- `DashboardCardTile` local `z-10`; `dialog.tsx`.
- `shadow-sm` on minor surfaces (cards/inputs already handled or out of scope).
- Any new tokens or stacking-context refactors.

## Testing strategy (Vitest + RTL)

- **Adoption assertions (where reachable):** the two overlay popovers are exercised
  by existing suites — `chartActionsMenu.test.tsx` (open the menu → panel has
  `z-[var(--z-dropdown)]` + `shadow-[var(--elevation-2)]`) and
  `tileSizeControl.test.tsx` (open the panel → same). The `AppShell` skip-nav class
  is a static `focus:`-prefixed class always present in `className`, assertable if a
  test renders `AppShell`.
- **Not unit-assertable:** `TopBar`/`Sidebar` stacking and the `SemanticQueryBuilder`
  drag preview (only renders mid-drag) — verified by `tsc`, a per-file completeness
  read, and the production build succeeding. **Actual visual layering** (mobile
  sidebar overlay covering the topbar; popovers above content) is **not** jsdom-
  testable and requires a manual browser smoke (a user step, called out in the
  plan + docs).
- Existing layout/dashboard/chart suites must stay green (the swaps are className-only).

## Definition of done (golden rule #5)

- Adoption assertions for the two popovers; `tsc` + `lint` clean (no new warnings);
  full `pnpm test` green, run first-hand; production `pnpm build` succeeds.
- `docs/FRONTEND.md` notes the layout/overlay z-index + elevation now use the tokens,
  and records the manual-stacking-smoke step.
- No new public API; no structural changes.

## Follow-on (not now)

- `dialog.tsx` adopting `--z-modal` / `--elevation-4` once the user WIP lands.
- Page-level "wow" redesign of a hero screen.
