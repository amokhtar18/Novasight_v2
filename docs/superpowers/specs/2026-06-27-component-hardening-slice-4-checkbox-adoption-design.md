# Design — Component Hardening Slice 4: Checkbox Adoption

- **Date:** 2026-06-27
- **Status:** Approved (design); pending implementation plan
- **Area:** `frontend/` — chart-format panels + wizards that hand-roll checkboxes
- **Predecessors:** Slices 1–3 (hardened primitives, contract rollout, page adoption).
- **Golden rules in play:** #4 (thin slice), #5 (tested + typed + documented).

## Summary

33 bare `<input type="checkbox">` elements across 9 files render as **browser-native
checkboxes** (off-theme, especially in dark mode) — they were never styled. This slice
replaces them with the hardened `<Checkbox>` primitive (`@/components/ui/checkbox`,
which already carries `accent-primary`, the shared `focusRing`, and consistent
sizing), giving a **visible** theming/polish win and one consistent checkbox
everywhere. Behavior-preserving.

## Problem (audit findings)

Bare, unstyled checkboxes (no `className`) in:

| File | Count |
|------|-------|
| `components/chart/format/CartesianControls.tsx` | 9 |
| `components/chart/format/GaugeControls.tsx` | 6 |
| `components/chart/format/SharedFormatControls.tsx` | 6 |
| `components/chart/format/PieControls.tsx` | 3 |
| `components/chart/format/FunnelControls.tsx` | 2 |
| `components/chart/format/TreemapControls.tsx` | 2 |
| `components/pipeline/PipelineWizard.tsx` | 3 |
| `pages/Pipelines.tsx` | 1 |
| `components/schedule/SchedulesPanel.tsx` | 1 |

They render with the browser default look, inconsistent with the themed UI.

## Decisions (locked during brainstorming)

| Decision | Choice |
|----------|--------|
| Scope | Swap all 33 bare checkboxes to `<Checkbox>` across the 9 files, in one slice |
| Pattern | `<input type="checkbox" {checked} {onChange} … />` → `<Checkbox {checked} {onChange} … />` (primitive sets `type="checkbox"`) |
| Preserve | `checked`/`defaultChecked`, `onChange`, `id`, `aria-label`, `disabled`; surrounding `<label>` / `<Label htmlFor>` wrappers stay |
| Out of scope | `type="radio"`/`file`/`number` inputs; any new `Field`/label wiring (pure swap, no gold-plating) |

## Scope — the swap

For each bare checkbox: replace the `<input type="checkbox" … />` with
`<Checkbox … />`, dropping the explicit `type="checkbox"` (the primitive sets it)
and keeping every other prop. Import `Checkbox` from `@/components/ui/checkbox`
where the file doesn't already import it. Two wrapper patterns exist and are
unchanged:
- `<label className="flex items-center gap-2"><input…/>Text</label>` (format panels) — keep the `<label>` wrapper.
- `<div className="flex items-center gap-2"><input id…/><Label htmlFor…/></div>` (SharedFormatControls) — keep the `<Label>` and `id` binding.
- Table-cell checkboxes with `aria-label` (wizards) — keep `aria-label`.

## Out of scope

- Radio/file/number inputs.
- New label associations or `Field` adoption for these checkboxes.
- The compact `SemanticQueryBuilder` filter input, `dialog.tsx` (user WIP) — unrelated.

## Testing strategy (Vitest + RTL)

- **Regression (primary gate):** existing suites that exercise these controls must
  stay green — `formatControls.test.tsx` (chart-format panels) and
  `pipelines.test.tsx` (pipeline wizard). They toggle checkboxes by `role="checkbox"`
  / label and assert `onChange`; the swap preserves `role`, label association, and
  `checked`/`onChange`, so they pass unchanged.
- **Adoption assertion:** per modified file (or group), assert one swapped checkbox
  now renders with `accent-primary` (the hardened `<Checkbox>` class the bare
  `<input>` lacked), resolved via its preserved handle (`role="checkbox"` +
  accessible name, or `id`).

## Definition of done (golden rule #5)

- Vitest/RTL: adoption assertions added; `formatControls` + `pipelines` (and any
  other suite touching these files) stay green.
- `pnpm exec tsc --noEmit` and `pnpm lint` clean (no new warnings).
- Full `pnpm test` green, run first-hand.
- `docs/FRONTEND.md` control-contract note updated (checkboxes use the primitive).
- No new public API; behavior preserved.

## Follow-on (not now)

- Layout z-index/elevation token rollout (TopBar/Sidebar/AppShell/popovers).
- `dialog.tsx` hardening (still blocked on user WIP).
- Page-level redesign of a hero screen.
