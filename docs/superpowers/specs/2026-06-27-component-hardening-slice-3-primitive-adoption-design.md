# Design — Component Hardening Slice 3: Adopt Hardened Primitives in Pages

- **Date:** 2026-06-27
- **Status:** Approved (design); pending implementation plan
- **Area:** `frontend/` — pages/components that hand-roll form controls
- **Predecessors:** Slice 1 (hardened core controls + tokens), Slice 2 (rolled contract to interactive primitives).
- **Golden rules in play:** #4 (thin slice), #5 (tested + typed + documented).

## Summary

Slices 1–2 hardened the `ui/` primitives. But several pages still **hand-roll
`<input>`/`<textarea>`** with the *old* inline styling — including
`focus-visible:ring-1` (more divergent than even the pre-hardening primitives).
This slice replaces those hand-rolled full-size text controls with the hardened
`<Input>` / `<Textarea>` primitives, so they inherit the shared `focusRing`, the
token-driven shadow, and the `invalid` capability, and so the duplicated class
strings are deleted.

Behavior-preserving: every behavioral prop and accessibility handle is kept
identical, so existing tests and a11y are unaffected.

## Problem (audit findings)

Hand-rolled full-size text controls using the old inline style
(`... shadow-sm ... focus-visible:ring-1 focus-visible:ring-ring`):

- `pages/Assistant.tsx:208` — `<input>` (chat message box).
- `pages/DashboardDetail.tsx:359` — `<textarea>` (add-to-dashboard text/markdown).
- `pages/DbtModels.tsx:406` — `<textarea>` (SQL, monospace).
- `components/chart/NLChartPanel.tsx:133` — `<textarea>` (NL chart prompt, no-resize).

These bypass the hardened primitives entirely; their focus ring (`ring-1`, no
offset) differs from the shared `focusRing` (`ring-2` + offset).

## Decisions (locked during brainstorming)

| Decision | Choice |
|----------|--------|
| Scope | Replace the **4 full-size text controls** above with `<Input>`/`<Textarea>` |
| Behavior | Preserve every behavioral prop + a11y handle (`id`, `aria-label`, `placeholder`, `aria-describedby`, `rows`, `maxLength`, `disabled`, `value`/`onChange`) |
| Special styling | Keep via `className`: `font-mono` (DbtModels SQL), `resize-none` (NLChartPanel) |
| Assistant input height | `h-10` → `h-9` (Input default `md`) — intended; aligns with the adjacent Send button |
| Checkboxes (~25 raw `type="checkbox"`) | **Excluded** — separate, larger `<Checkbox>`-adoption slice |
| `type="file"` / `type="number"` inputs (UploadCard, TileSizeControl) | **Excluded** — specialized controls |
| `SemanticQueryBuilder.tsx:462` compact filter input (`h-7`/`text-xs`) | **Excluded** — standard primitive would visibly enlarge it in the dense builder (debatable design change) |

## Scope — exact changes

For each site: replace the raw element + its inline `className` with the hardened
primitive, keeping the listed props. Drop the inline border/bg/shadow/focus
classes (the primitive supplies them). Import `Input`/`Textarea` from
`@/components/ui/input` / `@/components/ui/textarea` where not already imported.

1. **`Assistant.tsx`** — `<input … />` → `<Input value … onChange … placeholder="Ask, chart, or summarize…" aria-label="Message" maxLength={2000} />`. (Input is `w-full` by default; height becomes `h-9`.)
2. **`DashboardDetail.tsx`** — `<textarea … />` → `<Textarea id="ao-text" value … onChange … rows={5} placeholder={…} />`. (`<Input>` is already imported in this file; add `Textarea`.)
3. **`DbtModels.tsx`** — `<textarea … />` → `<Textarea id="dm-sql" value … onChange … rows={6} placeholder={…} className="font-mono" />`. (`<Input>` already imported; add `Textarea`.)
4. **`NLChartPanel.tsx`** — `<textarea … />` → `<Textarea id="nl-chart-prompt" value … onChange … placeholder={…} maxLength={MAX_CHARS} rows={3} disabled={isPending} aria-describedby="nl-chart-hint" className="resize-none" />`.

### Behavior change to note

`Assistant.tsx` message input height moves `h-10` → `h-9` (the hardened Input
default). Intended — it aligns with the `h-9` Send button beside it.

## Out of scope

- Raw `type="checkbox"` controls (chart format panels, wizards) → `<Checkbox>` is a later slice.
- `type="file"` (UploadCard) and `type="number"` (TileSizeControl) inputs.
- `SemanticQueryBuilder.tsx:462` compact filter input.
- Any new props on the primitives.

## Testing strategy (Vitest + RTL)

- **Preserve handles:** confirm existing tests for these screens still pass
  unchanged (they query by `aria-label`/`placeholder`/`label`/`id`, all preserved).
- **Adoption assertion:** for each swapped control, assert it now renders the
  shared focus ring — `toHaveClass("focus-visible:ring-offset-2")` (the marker
  the old `ring-1` styling lacked). Resolve the control via its preserved handle
  (e.g. `getByLabelText("Message")`, `getByLabelText` via the `<Label htmlFor>`,
  or `getByPlaceholderText`).
- Preserve special styling assertions where meaningful: DbtModels textarea has
  `font-mono`; NLChartPanel textarea has `resize-none`.

## Definition of done (golden rule #5)

- Vitest/RTL: the adoption assertions above, plus existing screen tests green.
- `pnpm exec tsc --noEmit` and `pnpm lint` clean (no new warnings).
- Full `pnpm test` green, run first-hand.
- `docs/FRONTEND.md` control-contract section notes that pages consume the
  hardened `Input`/`Textarea` (no more hand-rolled text controls in these screens).
- No new public API; behavior preserved except the noted `h-10→h-9`.

## Follow-on (not now)

- `<Checkbox>` adoption across the chart-format panels and wizards.
- The compact `SemanticQueryBuilder` filter input (needs a size/typography decision).
- `dialog.tsx` hardening (still blocked on user WIP).
