# Superset-parity Slice A2 (Per-type formatting) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make NovaSight's chart formatting type-aware with parity to Superset's per-type "Customize" panel: a v2 `ChartSpec` whose shared `ChartOptions` carries cross-type chrome and a nested `type_options` carries one option group per chart family (cartesian/pie/gauge/funnel/radar/treemap/number), honoured by the renderer and edited by a type-aware controls panel.

**Architecture:** Fresh-start, breaking change — `CHART_SPEC_VERSION` goes `"1"` → `"2"`; all type-specific options (including today's flat `stacked`/`percent`/`y_min`/`y_max`/`log_scale`/axis labels) move into `type_options.<family>`; the legacy flat fields are removed. v1 specs are NOT migrated. The renderer reads shared chrome + the family group; `FormatControls` becomes a `type → family` registry rendering shared sections + the one family section.

**Tech Stack:** Backend — Python 3.12, FastAPI, Pydantic v2, pytest. Frontend — React + TS, Vite, ECharts, Vitest + RTL.

## Global Constraints

- Formatting is **display-only**: no option here touches the query, the data, tenancy, or SQL. Golden rules #1–#3 are satisfied trivially (palette still derives from the theme; nothing environment/tenant-specific is hardcoded).
- `CHART_SPEC_VERSION` MUST become `"2"`. No v1 back-compat; no migration code.
- Family grouping (NOT a strict 14-way union): families are `cartesian` (bar, hbar, line, area, combo, scatter), `pie` (pie, donut), `gauge`, `funnel`, `radar`, `treemap`, `number`. `table` has no `type_options` in A2.
- `frontend/src/types/api.ts` mirrors the backend schema field-for-field, snake_case.
- Definition of done (golden rule #5): each task green on its tests; slice ends with `cd backend && .venv/Scripts/pytest.exe && .venv/Scripts/ruff.exe check . && .venv/Scripts/mypy.exe app` and `cd frontend && pnpm exec tsc --noEmit && pnpm lint` + tests all passing; `docs/CHART_SPEC.md` rewritten for v2.
- TOOLCHAIN: `uv` is NOT installed — run backend tools via `backend/.venv/Scripts/{pytest,ruff,mypy}.exe`. pnpm is on PATH. Use the Bash tool (Git Bash), not PowerShell.
- Branch: work on `feat/phase-2-widen` directly (no feature branch unless instructed).

---

### Task 1: Backend — v2 shared `ChartOptions` (chrome) + version bump

**Files:**
- Modify: `backend/app/schemas/chart.py` (`NumberFormat`, replace `ChartOptions`, bump `CHART_SPEC_VERSION`)
- Modify: `docs/examples/chart-spec.example.json` (rewrite `options` for v2)
- Test: `backend/tests/test_chart_spec.py` (replace the v1 options tests)

**Interfaces:**
- Produces (Pydantic models in `chart.py`):
  - `LegendOptions{show: bool=True, position: Literal["top","bottom","left","right"]="top", type: Literal["scroll","plain"]="scroll", margin: int|None=None, sort: Literal["none","asc","desc"]="none"}`
  - `LabelOptions{show: bool=False, position: str|None=None, template: str|None=None, threshold: float|None=None}`
  - `TooltipOptions{mode: Literal["item","axis","rich"]="axis", sort_by_metric: bool=False, show_total: bool=False, show_percentage: bool=False, time_format: str|None=None}`
  - `NumberFormat` gains `prefix: str|None=None`, `suffix: str|None=None`.
  - `ChartOptions{title: str|None=None, color_scheme: str|None=None, palette: list[HexColor]=[], legend: LegendOptions=…, number_format: NumberFormat=…, date_format: str|None=None, labels: LabelOptions=…, tooltip: TooltipOptions=…, sort: Literal[...]="none", type_options: "TypeOptions|None"=None}`  (`TypeOptions` is defined in Task 2; use a forward ref / `from __future__ import annotations` is already imported).
- Removed from `ChartOptions`: `stacked`, `percent`, `show_legend`, `legend_position`, `x_axis_label`, `y_axis_label`, `y_min`, `y_max`, `log_scale`, `data_labels`.

- [ ] **Step 1: Write the failing tests** — replace the existing `test_advanced_options_validate` and `test_invalid_palette_colour_is_rejected` in `backend/tests/test_chart_spec.py` with:

```python
def test_v2_version_is_current() -> None:
    from app.schemas.chart import CHART_SPEC_VERSION
    assert CHART_SPEC_VERSION == "2"


def test_v2_shared_chrome_options() -> None:
    spec = ChartSpec.model_validate(
        {
            "type": "bar",
            "query": {"metric_refs": ["sales.total"]},
            "encoding": {"x": "sales.region", "series": [{"field": "sales.total"}]},
            "options": {
                "title": "Sales",
                "color_scheme": "vibrant",
                "legend": {"show": True, "position": "bottom", "type": "plain", "sort": "desc"},
                "number_format": {"style": "currency", "currency": "$", "prefix": "≈", "suffix": " net"},
                "date_format": "%Y-%m",
                "labels": {"show": True, "threshold": 5, "template": "{value}"},
                "tooltip": {"mode": "rich", "show_total": True, "show_percentage": True},
            },
        }
    )
    assert spec.version == "2"
    assert spec.options.legend.position == "bottom"
    assert spec.options.legend.type == "plain"
    assert spec.options.number_format.prefix == "≈"
    assert spec.options.tooltip.mode == "rich"
    assert spec.options.labels.threshold == 5


def test_v2_options_default_empty() -> None:
    spec = ChartSpec.model_validate(
        {
            "type": "bar",
            "query": {"metric_refs": ["sales.total"]},
            "encoding": {"x": "sales.region", "series": [{"field": "sales.total"}]},
        }
    )
    assert spec.options.legend.show is True
    assert spec.options.tooltip.mode == "axis"
    assert spec.options.labels.show is False
    assert spec.options.type_options is None


def test_v2_rejects_legacy_flat_options() -> None:
    # Legacy flat fields are gone; Pydantic ignores unknown keys by default, so assert
    # the model has no such attribute rather than expecting an error.
    spec = ChartSpec.model_validate(
        {
            "type": "bar",
            "query": {"metric_refs": ["sales.total"]},
            "encoding": {"x": "sales.region", "series": [{"field": "sales.total"}]},
            "options": {"stacked": True},
        }
    )
    assert not hasattr(spec.options, "stacked")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/pytest.exe tests/test_chart_spec.py -k "v2_" -v`
Expected: FAIL (version is "1"; nested options don't exist).

- [ ] **Step 3: Implement** — in `backend/app/schemas/chart.py`: set `CHART_SPEC_VERSION = "2"`. Add `prefix`/`suffix` to `NumberFormat`. Add the three submodels and replace `ChartOptions`:

```python
class LegendOptions(BaseModel):
    show: bool = True
    position: Literal["top", "bottom", "left", "right"] = "top"
    type: Literal["scroll", "plain"] = "scroll"
    margin: int | None = Field(default=None, ge=0, le=200)
    sort: Literal["none", "asc", "desc"] = "none"


class LabelOptions(BaseModel):
    show: bool = False
    position: str | None = None
    template: str | None = Field(default=None, max_length=200)
    threshold: float | None = Field(default=None, ge=0)


class TooltipOptions(BaseModel):
    mode: Literal["item", "axis", "rich"] = "axis"
    sort_by_metric: bool = False
    show_total: bool = False
    show_percentage: bool = False
    time_format: str | None = Field(default=None, max_length=64)


class ChartOptions(BaseModel):
    """Display-only options (v2). Cross-type chrome here; per-type options in type_options."""

    title: str | None = None
    color_scheme: str | None = Field(default=None, max_length=64)
    palette: list[HexColor] = Field(default_factory=list, max_length=24)
    legend: LegendOptions = Field(default_factory=LegendOptions)
    number_format: NumberFormat = Field(default_factory=NumberFormat)
    date_format: str | None = Field(default=None, max_length=64)
    labels: LabelOptions = Field(default_factory=LabelOptions)
    tooltip: TooltipOptions = Field(default_factory=TooltipOptions)
    # Client-side category reorder (distinct from query.order server sort).
    sort: Literal["none", "value_desc", "value_asc", "label_asc", "label_desc"] = "none"
    type_options: TypeOptions | None = None
```

Add `prefix`/`suffix` to `NumberFormat` (after `currency`):

```python
    prefix: str | None = Field(default=None, max_length=8)
    suffix: str | None = Field(default=None, max_length=8)
```

`TypeOptions` is defined in Task 2; since `from __future__ import annotations` is at the top of the file, the forward reference resolves. Add `model_rebuild()` at the end of Task 2.

- [ ] **Step 4: Run tests** — `cd backend && .venv/Scripts/pytest.exe tests/test_chart_spec.py -k "v2_" -v` → PASS. (The canonical round-trip test will fail until Step 5.)

- [ ] **Step 5: Rewrite the canonical fixture `options` block** in `docs/examples/chart-spec.example.json` to the v2 shape (replace the entire `"options": {…}` object):

```json
  "options": {
    "title": "Monthly sales vs returns",
    "color_scheme": null,
    "palette": [],
    "legend": { "show": true, "position": "top", "type": "scroll", "margin": null, "sort": "none" },
    "number_format": { "style": "plain", "decimals": null, "compact": false, "currency": null, "prefix": null, "suffix": null },
    "date_format": null,
    "labels": { "show": false, "position": null, "template": null, "threshold": null },
    "tooltip": { "mode": "axis", "sort_by_metric": false, "show_total": false, "show_percentage": false, "time_format": null },
    "sort": "none",
    "type_options": null
  }
```

Also change the top-level `"version": "1"` to `"version": "2"` and update `test_fixture_uses_current_version` to assert `"2"`.

- [ ] **Step 6: Run the full chart-spec suite** — `cd backend && .venv/Scripts/pytest.exe tests/test_chart_spec.py -v` → PASS (round-trip green). Then `.venv/Scripts/ruff.exe check app/schemas/chart.py` and `.venv/Scripts/mypy.exe app/schemas/chart.py`.

> NOTE: backend `pytest` will have OTHER failures now (NL→chart and chart-API tests build v1 options). Those are fixed in Task 2's step where the shared+family schema is complete, and any test referencing removed flat fields is updated. Do not chase them here beyond `test_chart_spec.py`.

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/chart.py backend/tests/test_chart_spec.py docs/examples/chart-spec.example.json
git commit -m "feat(chart)!: v2 shared ChartOptions chrome + version bump (Slice A2)"
```

---

### Task 2: Backend — `TypeOptions` + per-family option models

**Files:**
- Modify: `backend/app/schemas/chart.py` (add family models + `TypeOptions`, then `ChartOptions.model_rebuild()`)
- Test: `backend/tests/test_chart_spec.py`
- Modify (only if they reference removed flat fields): any backend test that constructs `ChartOptions` with `stacked`/`y_min`/etc. — grep first.

**Interfaces:**
- Produces:
  - `CartesianOptions{stacked: bool=False, percent: bool=False, only_total: bool=False, label_threshold: float|None=None, area_opacity: float|None(ge=0,le=1)=None, markers: bool=False, marker_size: int|None(ge=1,le=50)=None, smooth: bool=False, x_axis_label: str|None=None, y_axis_label: str|None=None, x_label_rotation: Literal[0,45,90]|None=None, x_label_interval: Literal["auto","all"]="auto", y_min: float|None=None, y_max: float|None=None, log_scale: bool=False, minor_ticks: bool=False, minor_split_line: bool=False, data_zoom: bool=False, sort_series: Literal["none","asc","desc"]="none"}`
  - `PieOptions{label_type: Literal["category","value","percent","category_value","value_percent","category_value_percent"]="value", inner_radius: int|None(ge=0,le=100)=None, outer_radius: int|None(ge=0,le=100)=None, rose_type: Literal["none","area","radius"]="none", labels_outside: bool=False, label_line: bool=False, show_total: bool=False, show_labels_threshold: float|None=None, group_others_threshold: float|None=None}`
  - `GaugeOptions{min: float|None=None, max: float|None=None, start_angle: float|None=None, end_angle: float|None=None, show_pointer: bool=True, show_progress: bool=False, round_cap: bool=False, show_axis_tick: bool=False, show_split_line: bool=False, split_number: int|None(ge=3,le=30)=None, intervals: list[float]=[], interval_colors: list[HexColor]=[], font_size: int|None(ge=10,le=20)=None, animation: bool=True}` with a validator: if `intervals` and `interval_colors` are both non-empty, lengths must match.
  - `FunnelOptions{label_type: Literal["none","value","percent","category","category_value","value_percent","all"]="value", tooltip_label_type: Literal["value","percent","category","category_value","value_percent","all"]="value", show_labels: bool=True, show_tooltip_labels: bool=True}`
  - `RadarOptions{shape: Literal["polygon","circle"]="polygon", label_type: Literal["value","category_value"]="value", label_position: str|None=None, metric_bounds: dict[FieldName, "MetricBound"]={}}` where `MetricBound{min: float|None=None, max: float|None=None}`.
  - `TreemapOptions{show_labels: bool=True, show_upper_labels: bool=False, label_type: Literal["key","value","key_value"]="key"}`
  - `NumberOptions{subheader: str|None(max_length=200)=None, subtitle: str|None(max_length=200)=None, header_font_size: int|None(ge=8,le=120)=None, subheader_font_size: int|None(ge=8,le=120)=None}`
  - `TypeOptions{cartesian: CartesianOptions|None=None, pie: PieOptions|None=None, gauge: GaugeOptions|None=None, funnel: FunnelOptions|None=None, radar: RadarOptions|None=None, treemap: TreemapOptions|None=None, number: NumberOptions|None=None}`

- [ ] **Step 1: Write the failing tests** — append to `backend/tests/test_chart_spec.py`:

```python
def test_type_options_cartesian_and_pie() -> None:
    spec = ChartSpec.model_validate(
        {
            "type": "bar",
            "query": {"metric_refs": ["s.total"]},
            "encoding": {"x": "s.region", "series": [{"field": "s.total"}]},
            "options": {
                "type_options": {
                    "cartesian": {"stacked": True, "percent": True, "area_opacity": 0.4, "y_min": 0, "log_scale": True},
                    "pie": {"rose_type": "area", "inner_radius": 50, "label_type": "value_percent"},
                }
            },
        }
    )
    assert spec.options.type_options.cartesian.percent is True
    assert spec.options.type_options.cartesian.area_opacity == 0.4
    assert spec.options.type_options.pie.rose_type == "area"


def test_gauge_interval_colors_length_must_match() -> None:
    with pytest.raises(ValidationError, match="interval"):
        ChartSpec.model_validate(
            {
                "type": "gauge",
                "query": {"metric_refs": ["s.total"]},
                "encoding": {"series": [{"field": "s.total"}]},
                "options": {"type_options": {"gauge": {"intervals": [50, 80], "interval_colors": ["#ff0000"]}}},
            }
        )


def test_cartesian_area_opacity_range() -> None:
    with pytest.raises(ValidationError):
        ChartSpec.model_validate(
            {
                "type": "area",
                "query": {"metric_refs": ["s.total"]},
                "encoding": {"x": "s.d", "series": [{"field": "s.total"}]},
                "options": {"type_options": {"cartesian": {"area_opacity": 2}}},
            }
        )


def test_radar_metric_bounds_and_treemap_and_number() -> None:
    spec = ChartSpec.model_validate(
        {
            "type": "radar",
            "query": {"metric_refs": ["s.a", "s.b"]},
            "encoding": {"x": "s.region", "series": [{"field": "s.a"}, {"field": "s.b"}]},
            "options": {"type_options": {"radar": {"shape": "circle", "metric_bounds": {"s.a": {"min": 0, "max": 100}}}}},
        }
    )
    assert spec.options.type_options.radar.shape == "circle"
    assert spec.options.type_options.radar.metric_bounds["s.a"].max == 100
```

- [ ] **Step 2: Run tests to verify they fail** — `cd backend && .venv/Scripts/pytest.exe tests/test_chart_spec.py -k "type_options or gauge_interval or area_opacity or radar_metric" -v` → FAIL.

- [ ] **Step 3: Implement the family models + `TypeOptions`** in `backend/app/schemas/chart.py` (place ABOVE `ChartOptions`, since `ChartOptions` references `TypeOptions`; with `from __future__ import annotations` order is flexible, but define them before the `model_rebuild()` call). Use the exact field definitions from the Interfaces block above. The gauge validator:

```python
class GaugeOptions(BaseModel):
    min: float | None = None
    max: float | None = None
    start_angle: float | None = None
    end_angle: float | None = None
    show_pointer: bool = True
    show_progress: bool = False
    round_cap: bool = False
    show_axis_tick: bool = False
    show_split_line: bool = False
    split_number: int | None = Field(default=None, ge=3, le=30)
    intervals: list[float] = Field(default_factory=list, max_length=12)
    interval_colors: list[HexColor] = Field(default_factory=list, max_length=12)
    font_size: int | None = Field(default=None, ge=10, le=20)
    animation: bool = True

    @model_validator(mode="after")
    def _intervals_match_colors(self) -> GaugeOptions:
        if self.intervals and self.interval_colors and len(self.intervals) != len(self.interval_colors):
            raise ValueError("gauge interval_colors length must match intervals length")
        return self
```

Write the other family models per the Interfaces block (each a plain `BaseModel` with the listed fields + `Field(ge=…, le=…)` ranges). `MetricBound` and `RadarOptions.metric_bounds: dict[FieldName, MetricBound]`. Then `TypeOptions` aggregating them. At the END of the file (after `ChartSpec`), add:

```python
ChartOptions.model_rebuild()
```

- [ ] **Step 4: Run tests** — `cd backend && .venv/Scripts/pytest.exe tests/test_chart_spec.py -v` → PASS.

- [ ] **Step 5: Fix any other backend tests referencing removed flat options** — run `grep -rn "stacked\|y_min\|y_max\|log_scale\|data_labels\|legend_position\|show_legend\|x_axis_label\|y_axis_label" backend/tests` and `backend/app/ai`. For each test/fixture or NL→chart prompt-example that builds v1 `ChartOptions`, update it to the v2 shape (move those keys under `type_options.cartesian` or into `legend`/`labels`). Then run the affected suites:
  `cd backend && .venv/Scripts/pytest.exe tests/test_nl_to_chart.py tests/test_charts_api.py -v` → PASS.

- [ ] **Step 6: Backend gate** — `cd backend && .venv/Scripts/pytest.exe -q && .venv/Scripts/ruff.exe check . && .venv/Scripts/mypy.exe app` → all green.

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/chart.py backend/tests
git commit -m "feat(chart): v2 type_options per-family models + validation (Slice A2)"
```

---

### Task 3: Frontend — mirror v2 types

**Files:**
- Modify: `frontend/src/types/api.ts` (replace `ChartOptions`/`NumberFormat`; add submodels + `TypeOptions` + family interfaces)
- Test: `frontend/src/test/chartSpec.test.ts`

**Interfaces:**
- Produces TS interfaces mirroring Task 1 + Task 2 exactly (snake_case): `LegendOptions`, `LabelOptions`, `TooltipOptions`, `NumberFormat` (+`prefix`/`suffix`), `CartesianOptions`, `PieOptions`, `GaugeOptions`, `FunnelOptions`, `RadarOptions` (+`MetricBound`), `TreemapOptions`, `NumberOptions`, `TypeOptions`, and the rebuilt `ChartOptions{ title?, color_scheme?, palette?, legend?, number_format?, date_format?, labels?, tooltip?, sort?, type_options? }`. Every field optional on the TS side (request-shape).

- [ ] **Step 1: Implement** the TS mirror in `frontend/src/types/api.ts`, replacing the current `NumberFormat` and `ChartOptions` interfaces and removing the flat fields. Use literal unions matching the backend `Literal`s exactly (e.g. `legend.position: "top"|"bottom"|"left"|"right"`, `pie.label_type` 6-way union, etc.).

- [ ] **Step 2: Write the assignability test** — append to `frontend/src/test/chartSpec.test.ts`:

```typescript
import type { ChartOptions } from "@/types/api";

test("v2 ChartOptions accepts nested chrome + type_options", () => {
  const o: ChartOptions = {
    title: "X",
    legend: { show: true, position: "bottom", type: "plain", sort: "desc" },
    number_format: { style: "currency", currency: "$", prefix: "≈", suffix: "/u" },
    labels: { show: true, threshold: 5, template: "{value}" },
    tooltip: { mode: "rich", show_total: true, show_percentage: true },
    type_options: {
      cartesian: { stacked: true, percent: true, area_opacity: 0.4, y_min: 0, log_scale: true, markers: true, smooth: true },
      pie: { rose_type: "area", inner_radius: 50, label_type: "value_percent", show_total: true },
      gauge: { start_angle: 225, end_angle: -45, intervals: [50, 80, 100], interval_colors: ["#0f0", "#ff0", "#f00"] },
      radar: { shape: "circle", metric_bounds: { "s.a": { min: 0, max: 100 } } },
      number: { subheader: "vs LY", header_font_size: 40 },
    },
  };
  expect(o.type_options?.cartesian?.percent).toBe(true);
  expect(o.type_options?.gauge?.interval_colors?.length).toBe(3);
});
```

- [ ] **Step 3: Typecheck + test** — `cd frontend && pnpm exec tsc --noEmit && pnpm test -- chartSpec`. Expected: the existing `chartSpec` tests that referenced v1 flat options will FAIL TO COMPILE — update those existing test object literals in this file to the v2 shape as part of this step. Then green.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/api.ts frontend/src/test/chartSpec.test.ts
git commit -m "feat(types): mirror v2 ChartOptions + type_options (Slice A2)"
```

---

### Task 4: Frontend renderer — shared chrome (legend / labels / tooltip / number / date)

**Files:**
- Modify: `frontend/src/components/chart/ChartRenderer.tsx` (`buildEChartsOption` shared helpers)
- Test: `frontend/src/test/chartRenderer.test.ts`

**Interfaces:**
- Consumes v2 `ChartOptions` (Task 3).
- Produces updated internal helpers in `buildEChartsOption`: `legendBlock()` reads `options.legend.{show,position,type,margin}`; a shared `labelConfig(seriesType)` from `options.labels`; `tooltip` built from `options.tooltip.mode` (`item`/`axis`/`rich`→axis with all-series) + `show_total`/`show_percentage`; `fmt` honours `number_format.prefix`/`suffix`; a `dateFmt` helper used for time-axis categories when `options.date_format` is set.
- Since later family tasks read `options.type_options?.<family>`, define a typed local accessor `const t = options.type_options ?? {}` once.

- [ ] **Step 1: Update `frontend/src/lib/chartFormat.ts`** to honour prefix/suffix:

```typescript
export function formatChartValue(value: number, nf?: NumberFormat): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "";
  const style = nf?.style ?? "plain";
  const decimals = nf?.decimals ?? null;
  const compact = nf?.compact ?? false;
  const body = compact ? compactNumber(value, decimals) : plainNumber(value, decimals);
  let out = body;
  if (style === "currency") out = `${nf?.currency ?? "$"}${body}`;
  else if (style === "percent") out = `${body}%`;
  return `${nf?.prefix ?? ""}${out}${nf?.suffix ?? ""}`;
}
```

- [ ] **Step 2: Write/extend the failing test** in `frontend/src/test/chartFormat.test.ts`:

```typescript
it("applies prefix and suffix", () => {
  expect(formatChartValue(5, { style: "plain", prefix: "≈", suffix: "/u" })).toBe("≈5/u");
});
```

Run `cd frontend && pnpm test -- chartFormat` → FAIL, then after Step 1 → PASS.

- [ ] **Step 3: Refactor the shared blocks in `buildEChartsOption`** (`ChartRenderer.tsx`). Replace the legend/label/tooltip derivations:

```typescript
const opts = spec.options ?? {};
const legend = opts.legend ?? {};
const showLegend = legend.show ?? true;
const labels = opts.labels ?? {};
const tip = opts.tooltip ?? {};
const t = opts.type_options ?? {};

const legendBlock = (): Record<string, unknown> | undefined => {
  if (!showLegend) return undefined;
  const pos = legend.position ?? "top";
  const base: Record<string, unknown> = {
    data: series.map(seriesLabel),
    textStyle: { color: theme.text },
    type: legend.type === "plain" ? "plain" : "scroll",
    ...(legend.margin != null ? { padding: legend.margin } : {}),
  };
  if (pos === "bottom") return { ...base, bottom: 0 };
  if (pos === "left") return { ...base, orient: "vertical", left: "left" };
  if (pos === "right") return { ...base, orient: "vertical", right: "right" };
  return { ...base, top: 0 };
};

const dataLabel = labels.show
  ? { show: true, color: theme.text, ...(labels.position ? { position: labels.position } : {}) }
  : undefined;

const tooltipTrigger = tip.mode === "item" ? "item" : "axis";
const axisTooltip = {
  trigger: tooltipTrigger,
  backgroundColor: theme.tooltipBg,
  borderColor: theme.tooltipBorder,
  textStyle: { color: theme.text },
  valueFormatter: (v: number | string) => fmt(Number(v)),
};
```

(Family tasks layer their specifics onto `dataLabel`/`legendBlock`/`t.<family>`.) Keep `itemTooltip` for pie/funnel/etc., switching its `trigger` to `tip.mode === "axis" ? "item" : tooltipTrigger` so single-series circular charts still use item tooltips.

- [ ] **Step 4: Update the existing `buildEChartsOption` tests** in `chartRenderer.test.ts` that construct v1 options (`show_legend`, `legend_position`, `data_labels`, `y_min`, etc.) to the v2 shape, and add one asserting `legend.type` maps to ECharts `type: "plain"`:

```typescript
it("maps legend.type plain and labels.show", () => {
  const opt = buildEChartsOption(
    { version: "2", type: "bar", query: { metric_refs: ["m"] },
      encoding: { x: "c", series: [{ field: "m" }] },
      options: { legend: { show: true, type: "plain" }, labels: { show: true } } },
    { columns: ["c", "m"], rows: [["a", 1]], row_count: 1 }
  ) as any;
  expect(opt.legend.type).toBe("plain");
});
```

Run `cd frontend && pnpm test -- chartRenderer` → PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/chartFormat.ts frontend/src/components/chart/ChartRenderer.tsx frontend/src/test/chartFormat.test.ts frontend/src/test/chartRenderer.test.ts
git commit -m "feat(chart): renderer honours v2 shared chrome (legend/labels/tooltip/number) (Slice A2)"
```

---

### Task 5: Frontend renderer — cartesian family options

**Files:**
- Modify: `frontend/src/components/chart/ChartRenderer.tsx` (bar/line/area/combo/hbar/scatter branches; register `DataZoomComponent`)
- Test: `frontend/src/test/chartRenderer.test.ts`

**Interfaces:**
- Consumes `options.type_options?.cartesian` (Task 3) + shared blocks (Task 4).
- Behaviour: `stacked`→`stack:"total"`; `percent`→stacked with each series normalised to 100% (compute per-category totals and divide) OR use ECharts `stack` + `stackStrategy`; `only_total`→show a single total label via `label` on last series; `area_opacity`→`areaStyle:{opacity}`; `markers`→`showSymbol:true,symbolSize:marker_size??6` (line/scatter); `smooth`→`smooth:true`; `x_label_rotation`→`xAxis.axisLabel.rotate`; `x_label_interval:"all"`→`axisLabel.interval:0`; `minor_ticks`/`minor_split_line`→axis `minorTick.show`/`minorSplitLine.show`; `data_zoom`→add `dataZoom:[{type:"inside"},{type:"slider"}]` and register `DataZoomComponent`; `sort_series`→reorder series by total asc/desc; `y_min`/`y_max`/`log_scale`/`x_axis_label`/`y_axis_label` come from `cartesian` now (not the removed flat fields). `valueAxis()` signature updated to take the cartesian group.

- [ ] **Step 1: Write the failing tests** — append to `chartRenderer.test.ts`:

```typescript
const cartSpec = (cartesian: any, type = "bar") => ({
  version: "2", type, query: { metric_refs: ["m"] },
  encoding: { x: "c", series: [{ field: "m" }] },
  options: { type_options: { cartesian } },
});
const cartData = { columns: ["c", "m"], rows: [["a", 1], ["b", 3]], row_count: 2 };

it("cartesian stacked + percent normalises series to 100", () => {
  const opt = buildEChartsOption(cartSpec({ stacked: true, percent: true }), cartData) as any;
  expect(opt.series[0].stack).toBe("total");
});
it("cartesian area_opacity + smooth + markers on line", () => {
  const opt = buildEChartsOption(cartSpec({ area_opacity: 0.3, smooth: true, markers: true }, "area"), cartData) as any;
  expect(opt.series[0].areaStyle.opacity).toBe(0.3);
  expect(opt.series[0].smooth).toBe(true);
  expect(opt.series[0].showSymbol).toBe(true);
});
it("cartesian data_zoom adds a dataZoom block and y bounds/log come from the group", () => {
  const opt = buildEChartsOption(cartSpec({ data_zoom: true, y_min: 0, y_max: 10, log_scale: false }), cartData) as any;
  expect(Array.isArray(opt.dataZoom)).toBe(true);
  expect(opt.yAxis.min).toBe(0);
  expect(opt.yAxis.max).toBe(10);
});
```

- [ ] **Step 2: Run** `cd frontend && pnpm test -- chartRenderer` → the three new tests FAIL.

- [ ] **Step 3: Implement.** Register `DataZoomComponent`: add to the imports from `echarts/components` and the `echarts.use([...])` list. Update `valueAxis()` to read bounds/log from the cartesian group (pass `c = t.cartesian ?? {}`):

```typescript
import { DataZoomComponent } from "echarts/components";
// add DataZoomComponent to echarts.use([...])
```

In the bar/line/area/combo branch, build series with the cartesian options and assemble the option object with `dataZoom`, axis rotation/interval, minor ticks. Concretely, replace the `seriesList` builder + return for that branch:

```typescript
const c = t.cartesian ?? {};
const isArea = spec.type === "area";
const isCombo = spec.type === "combo";
let ordered = series;
if (c.sort_series && c.sort_series !== "none") {
  const totals = (s: typeof series[number]) =>
    srows.reduce((acc, r) => acc + num(r[colIndex(s.field)]), 0);
  ordered = [...series].sort((a, b) =>
    c.sort_series === "asc" ? totals(a) - totals(b) : totals(b) - totals(a));
}
const seriesList = ordered.map((s, si) => {
  const valIdx = colIndex(s.field);
  const seriesType = isCombo ? (si === 0 ? "bar" : "line") : isArea || spec.type === "line" ? "line" : "bar";
  return {
    name: seriesLabel(s),
    type: seriesType as "bar" | "line",
    stack: c.stacked || c.percent ? "total" : undefined,
    areaStyle: isArea ? { opacity: c.area_opacity ?? 0.5 } : undefined,
    smooth: c.smooth || undefined,
    showSymbol: seriesType === "line" ? (c.markers ?? false) : undefined,
    symbolSize: c.marker_size ?? undefined,
    itemStyle: s.color ? { color: s.color } : undefined,
    label: c.only_total && si === ordered.length - 1
      ? { show: true, position: "top", color: theme.text }
      : dataLabel,
    data: srows.map((row) => num(row[valIdx])),
  };
});

return toOption({
  color: palette,
  textStyle: { color: theme.text },
  title: titleBlock,
  tooltip: axisTooltip,
  grid: { left: 8, right: 16, top: options.title ? 48 : 24, bottom: c.data_zoom ? 48 : 8, containLabel: true },
  legend: legendBlock(),
  ...(c.data_zoom ? { dataZoom: [{ type: "inside" }, { type: "slider" }] } : {}),
  xAxis: {
    type: "category",
    name: c.x_axis_label ?? undefined,
    data: categories,
    axisLabel: {
      rotate: c.x_label_rotation ?? (categories.length > 6 ? 45 : 0),
      interval: c.x_label_interval === "all" ? 0 : "auto",
      color: theme.text,
    },
    axisLine: { lineStyle: { color: theme.axisLine } },
    minorTick: { show: c.minor_ticks ?? false },
    nameTextStyle: { color: theme.text },
  },
  yAxis: valueAxis(theme, c, fmt, c.y_axis_label),
  series: seriesList,
});
```

For `percent` (100% stacked), after building `seriesList`, if `c.percent`, normalise: for each category index, divide each series' value by the category total ×100. Implement as a post-map over `seriesList[*].data`:

```typescript
if (c.percent) {
  const totalsPerCat = categories.map((_, i) =>
    seriesList.reduce((acc, s) => acc + (s.data[i] as number), 0) || 1);
  for (const s of seriesList) s.data = (s.data as number[]).map((v, i) => (v / totalsPerCat[i]) * 100);
}
```

Update `valueAxis(theme, c, fmt, label)` to read `c.log_scale`, `c.y_min`, `c.y_max`. Apply the same pattern to the `hbar` branch (bounds/stack from `c`) and the `scatter` branch (markers/marker_size; scatter ignores stack/area).

- [ ] **Step 4: Run** `cd frontend && pnpm test -- chartRenderer` → PASS. Also `pnpm exec tsc --noEmit`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/chart/ChartRenderer.tsx frontend/src/test/chartRenderer.test.ts
git commit -m "feat(chart): renderer cartesian family options (Slice A2)"
```

---

### Task 6: Frontend renderer — pie/donut family options

**Files:**
- Modify: `frontend/src/components/chart/ChartRenderer.tsx` (pie/donut branch)
- Test: `frontend/src/test/chartRenderer.test.ts`

**Interfaces:** Consumes `options.type_options?.pie`. Behaviour: `inner_radius`/`outer_radius`→`radius:[inner%,outer%]` (donut default inner 50 when unset, pie 0); `rose_type`→`roseType:"area"|"radius"|false`; `labels_outside`→`label.position:"outside"` else `"inside"`; `label_line`→`labelLine.show`; `label_type`+`template`→`label.formatter`; `show_labels_threshold`→hide labels below %; `group_others_threshold`→fold slices below % into an "Other" datum; `show_total`→a center `graphic`/`title` text of the sum.

- [ ] **Step 1: Write the failing tests** — append:

```typescript
const pieData = { columns: ["c", "m"], rows: [["a", 1], ["b", 1], ["c", 8]], row_count: 3 };
it("pie rose_type + radius from group", () => {
  const opt = buildEChartsOption(
    { version: "2", type: "donut", query: { metric_refs: ["m"] },
      encoding: { x: "c", series: [{ field: "m" }] },
      options: { type_options: { pie: { rose_type: "area", inner_radius: 40, outer_radius: 70 } } } },
    pieData) as any;
  expect(opt.series[0].roseType).toBe("area");
  expect(opt.series[0].radius).toEqual(["40%", "70%"]);
});
it("pie groups slices below group_others_threshold into Other", () => {
  const opt = buildEChartsOption(
    { version: "2", type: "pie", query: { metric_refs: ["m"] },
      encoding: { x: "c", series: [{ field: "m" }] },
      options: { type_options: { pie: { group_others_threshold: 20 } } } },
    pieData) as any;
  const names = opt.series[0].data.map((d: any) => d.name);
  expect(names).toContain("Other");
});
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement** the pie/donut branch to read `const p = t.pie ?? {}`. Compute the slice data, apply `group_others_threshold` (sum the below-threshold slices into `{name:"Other", value}`), set `radius` (`[`${p.inner_radius ?? (spec.type==="donut"?50:0)}%`, `${p.outer_radius ?? 70}%`]`), `roseType: p.rose_type && p.rose_type!=="none" ? p.rose_type : undefined`, `label` with position/labelLine/formatter from `p.label_type`+`opts.labels.template`+`show_labels_threshold`. For `show_total`, add a centered `title: { text: fmt(total), left: "center", top: "center", textStyle:{color:theme.text} }` (replacing `titleBlock` only when no chart title, else use a `graphic`).

- [ ] **Step 4: Run** `pnpm test -- chartRenderer` → PASS; `pnpm exec tsc --noEmit`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/chart/ChartRenderer.tsx frontend/src/test/chartRenderer.test.ts
git commit -m "feat(chart): renderer pie/donut family options (Slice A2)"
```

---

### Task 7: Frontend renderer — gauge family options

**Files:**
- Modify: `frontend/src/components/chart/ChartRenderer.tsx` (gauge branch)
- Test: `frontend/src/test/chartRenderer.test.ts`

**Interfaces:** Consumes `options.type_options?.gauge`. Behaviour: `min`/`max` (fallback to existing total-based default), `start_angle`/`end_angle`→`startAngle`/`endAngle`, `show_pointer`→`pointer.show`, `show_progress`→`progress.show`, `round_cap`→`progress.roundCap`, `show_axis_tick`→`axisTick.show`, `show_split_line`→`splitLine.show`, `split_number`→`splitNumber`, `intervals`+`interval_colors`→`axisLine.lineStyle.color` as `[[stop,color],…]` (normalise stops to 0..1 over max), `font_size`→`detail.fontSize`, `animation`→`animation`.

- [ ] **Step 1: Write the failing test** — append:

```typescript
it("gauge applies angles, intervals+colors, pointer/progress", () => {
  const opt = buildEChartsOption(
    { version: "2", type: "gauge", query: { metric_refs: ["m"] },
      encoding: { series: [{ field: "m" }] },
      options: { type_options: { gauge: { min: 0, max: 100, start_angle: 225, end_angle: -45,
        show_progress: true, round_cap: true, intervals: [50, 100], interval_colors: ["#0f0", "#f00"] } } } },
    { columns: ["m"], rows: [[42]], row_count: 1 }) as any;
  expect(opt.series[0].startAngle).toBe(225);
  expect(opt.series[0].progress.show).toBe(true);
  expect(opt.series[0].axisLine.lineStyle.color[0][1]).toBe("#0f0");
});
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement** the gauge branch reading `const g = t.gauge ?? {}`. Build `axisLine.lineStyle.color`: if `g.intervals.length`, map each interval bound to `[bound/max, g.interval_colors[i] ?? theme.palette[i]]`; else `[[1, theme.axisLine]]`. Set `min: g.min ?? options.y... (use g.min ?? 0)`, `max: g.max ?? Math.max(total*1.25,1)`, `startAngle`/`endAngle` when set, `pointer:{show:g.show_pointer ?? true}`, `progress:{show:g.show_progress ?? false, roundCap:g.round_cap ?? false}`, `axisTick:{show:g.show_axis_tick ?? false}`, `splitLine:{show:g.show_split_line ?? false}`, `splitNumber:g.split_number ?? undefined`, `detail:{formatter:(v)=>fmt(v), color:theme.text, fontSize:g.font_size ?? undefined}`, `animation:g.animation ?? true`.

- [ ] **Step 4: Run** `pnpm test -- chartRenderer` → PASS; tsc.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/chart/ChartRenderer.tsx frontend/src/test/chartRenderer.test.ts
git commit -m "feat(chart): renderer gauge family options (Slice A2)"
```

---

### Task 8: Frontend renderer — funnel, radar, treemap family options

**Files:**
- Modify: `frontend/src/components/chart/ChartRenderer.tsx` (funnel/radar/treemap branches)
- Test: `frontend/src/test/chartRenderer.test.ts`

**Interfaces:** Consumes `options.type_options?.{funnel,radar,treemap}`. Funnel: `label_type`/`show_labels`→`label.show`+`formatter`, `tooltip_label_type`/`show_tooltip_labels`. Radar: `shape`→`radar.shape:"circle"|"polygon"`, `label_type`/`label_position`→series `label`, `metric_bounds[field]`→per-indicator `max`/`min`. Treemap: `show_labels`→`label.show`, `show_upper_labels`→`upperLabel.show`, `label_type`→`label.formatter`.

- [ ] **Step 1: Write the failing tests** — append:

```typescript
it("radar shape circle + per-metric bounds", () => {
  const opt = buildEChartsOption(
    { version: "2", type: "radar", query: { metric_refs: ["a","b"] },
      encoding: { x: "c", series: [{ field: "a" }, { field: "b" }] },
      options: { type_options: { radar: { shape: "circle", metric_bounds: {} } } } },
    { columns: ["c","a","b"], rows: [["x",1,2],["y",3,4]], row_count: 2 }) as any;
  expect(opt.radar.shape).toBe("circle");
});
it("treemap upper labels + funnel label toggle", () => {
  const t = buildEChartsOption(
    { version: "2", type: "treemap", query: { metric_refs: ["m"] },
      encoding: { x: "c", series: [{ field: "m" }] },
      options: { type_options: { treemap: { show_upper_labels: true } } } },
    { columns: ["c","m"], rows: [["a",1]], row_count: 1 }) as any;
  expect(t.series[0].upperLabel.show).toBe(true);
});
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement** the three branches reading their family groups (`t.funnel`/`t.radar`/`t.treemap`), per the Interfaces. For radar `shape`, set `radar: { ..., shape: (t.radar?.shape ?? "polygon") }`; for `metric_bounds`, when building `indicator`, look up `t.radar?.metric_bounds?.[seriesField]` — note radar indicators are over the x-categories in the current code, so apply `metric_bounds` only if keyed by category; otherwise use the computed `maxVal`. (Keep current behaviour when `metric_bounds` is empty.) Treemap: `label:{show: t.treemap?.show_labels ?? true, ...}`, `upperLabel:{show: t.treemap?.show_upper_labels ?? false, color: theme.text}`. Funnel: `label:{show: t.funnel?.show_labels ?? true, color: theme.text, formatter: labelFormatterFor(t.funnel?.label_type)}`.

- [ ] **Step 4: Run** `pnpm test -- chartRenderer` → PASS; tsc.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/chart/ChartRenderer.tsx frontend/src/test/chartRenderer.test.ts
git commit -m "feat(chart): renderer funnel/radar/treemap family options (Slice A2)"
```

---

### Task 9: Frontend — NumberRenderer number-family options

**Files:**
- Modify: `frontend/src/components/chart/NumberRenderer.tsx`
- Test: `frontend/src/test/charts.test.tsx` (or a new `numberRenderer.test.tsx`)

**Interfaces:** Consumes `options.type_options?.number` + `options.number_format`. Renders the big value (formatted via `formatChartValue`), an optional `subheader` and `subtitle`, and applies `header_font_size`/`subheader_font_size` as inline `fontSize`.

- [ ] **Step 1: Read** `frontend/src/components/chart/NumberRenderer.tsx` to learn its current props/structure.

- [ ] **Step 2: Write the failing test** — create `frontend/src/test/numberRenderer.test.tsx`:

```typescript
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { NumberRenderer } from "@/components/chart/NumberRenderer";
import type { ChartSpec, QueryResponse } from "@/types/api";

const data: QueryResponse = { columns: ["m"], rows: [[1234]], row_count: 1 };
const spec: ChartSpec = {
  version: "2", type: "number", query: { metric_refs: ["m"] },
  encoding: { series: [{ field: "m" }] },
  options: { number_format: { compact: true }, type_options: { number: { subheader: "vs LY", header_font_size: 48 } } },
};

describe("NumberRenderer v2", () => {
  it("renders the compact value + subheader", () => {
    render(<NumberRenderer spec={spec} data={data} />);
    expect(screen.getByText(/1\.2K/)).toBeInTheDocument();
    expect(screen.getByText("vs LY")).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run** → FAIL.

- [ ] **Step 4: Implement** `NumberRenderer` to read `spec.options?.type_options?.number` and render the subheader/subtitle with the font sizes (inline `style={{ fontSize }}`), using `formatChartValue(value, spec.options?.number_format)` for the main value.

- [ ] **Step 5: Run** `pnpm test -- numberRenderer` → PASS; tsc.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/chart/NumberRenderer.tsx frontend/src/test/numberRenderer.test.tsx
git commit -m "feat(chart): NumberRenderer number-family options (Slice A2)"
```

---

### Task 10: Frontend — type-aware FormatControls

**Files:**
- Create: `frontend/src/components/chart/format/` — `index.tsx` (the type-aware `FormatControls` + `FAMILY_FOR_TYPE`), `SharedFormatControls.tsx`, `CartesianControls.tsx`, `PieControls.tsx`, `GaugeControls.tsx`, `FunnelControls.tsx`, `RadarControls.tsx`, `TreemapControls.tsx`, `NumberControls.tsx`
- Modify: `frontend/src/pages/Builder.tsx` (import the new `FormatControls`, remove the old inline one)
- Test: `frontend/src/test/formatControls.test.tsx` (create)

**Interfaces:**
- Produces `FormatControls({ options, setOptions, chartType }: { options: ChartOptions; setOptions: (o: ChartOptions) => void; chartType: ChartType })`.
- `FAMILY_FOR_TYPE: Record<ChartType, "cartesian"|"pie"|"gauge"|"funnel"|"radar"|"treemap"|"number"|null>` (table → null).
- Renders `SharedFormatControls` always + the one family sub-panel for `FAMILY_FOR_TYPE[chartType]` (none for `table`/`null`). Each family panel reads/writes `options.type_options.<family>` immutably.

- [ ] **Step 1: Write the failing test** — `frontend/src/test/formatControls.test.tsx`:

```typescript
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { FormatControls, FAMILY_FOR_TYPE } from "@/components/chart/format";
import type { ChartOptions } from "@/types/api";

const noop = () => {};
const base: ChartOptions = {};

describe("FormatControls type-awareness", () => {
  it("maps each chart type to the right family", () => {
    expect(FAMILY_FOR_TYPE.bar).toBe("cartesian");
    expect(FAMILY_FOR_TYPE.donut).toBe("pie");
    expect(FAMILY_FOR_TYPE.gauge).toBe("gauge");
    expect(FAMILY_FOR_TYPE.table).toBeNull();
  });
  it("shows cartesian section for bar, not pie", () => {
    render(<FormatControls options={base} setOptions={noop} chartType="bar" />);
    expect(screen.getByText(/stacked/i)).toBeInTheDocument();
    expect(screen.queryByText(/donut hole|inner radius/i)).not.toBeInTheDocument();
  });
  it("shows pie section for donut, not cartesian stacked", () => {
    render(<FormatControls options={base} setOptions={noop} chartType="donut" />);
    expect(screen.getByText(/inner radius/i)).toBeInTheDocument();
    expect(screen.queryByText(/^stacked$/i)).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run** `cd frontend && pnpm test -- formatControls` → FAIL (module missing).

- [ ] **Step 3: Implement** the `format/` directory. `index.tsx` defines `FAMILY_FOR_TYPE` and a `FormatControls` that renders `<SharedFormatControls>` + a `switch (FAMILY_FOR_TYPE[chartType])` choosing the family panel. Each panel is a small controlled component editing a slice of `options` (shared) or `options.type_options.<family>` via an immutable setter helper:

```typescript
function setFamily<K extends keyof NonNullable<ChartOptions["type_options"]>>(
  options: ChartOptions, family: K, patch: Partial<NonNullable<NonNullable<ChartOptions["type_options"]>[K]>>
): ChartOptions {
  const to = options.type_options ?? {};
  return { ...options, type_options: { ...to, [family]: { ...(to[family] ?? {}), ...patch } } };
}
```

Build each family panel's inputs from the spec's option list (Cartesian: stacked/percent/only_total/area_opacity/markers/marker_size/smooth/x_label_rotation/x_label_interval/y_min/y_max/log_scale/minor_ticks/minor_split_line/data_zoom/sort_series/x_axis_label/y_axis_label; Pie: label_type/inner_radius/outer_radius/rose_type/labels_outside/label_line/show_total/show_labels_threshold/group_others_threshold; Gauge, Funnel, Radar, Treemap, Number per the spec). `SharedFormatControls` edits title/color_scheme/legend/number_format(+prefix/suffix)/date_format/labels/tooltip/sort. Reuse the existing `Label`/`Select`/`Input` UI primitives and the `<details>` section pattern from the old `FormatControls`.

- [ ] **Step 4: Wire into Builder** — in `frontend/src/pages/Builder.tsx`, remove the old inline `FormatControls` function and its `FormatState`/`toChartOptions`/`fromChartOptions` (those are replaced in Task 11). Import `FormatControls` from `@/components/chart/format`. (The Builder state migration is Task 11; for now, render `<FormatControls options={semantic.spec.options ?? {}} setOptions={semantic.setOptions} chartType={semantic.chartType} />` — `setOptions` is added in Task 11. To keep this task self-contained and green, gate the Builder edit to Task 11: in THIS task only create the components + test them in isolation; do the Builder swap in Task 11.)

  → Adjust: in Task 10, do NOT modify `Builder.tsx`. Only create + unit-test the `format/` components. The Builder swap happens in Task 11.

- [ ] **Step 5: Run** `cd frontend && pnpm test -- formatControls && pnpm exec tsc --noEmit` → PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/chart/format frontend/src/test/formatControls.test.tsx
git commit -m "feat(builder): type-aware FormatControls per chart family (Slice A2)"
```

---

### Task 11: Frontend — Builder v2 options state + wiring; full verification + docs

**Files:**
- Modify: `frontend/src/pages/Builder.tsx` (`useSemanticBuilder` options state → v2 `ChartOptions`; `loadSpec`; render new `FormatControls`)
- Modify: `docs/CHART_SPEC.md` (rewrite the options section for v2)
- Test: `frontend/src/test/builderQuery.test.ts` or `builderLoadSpec.test.tsx` (extend for options)

**Interfaces:**
- The builder holds `options: ChartOptions` (v2) in state with `setOptions`, replacing the old `FormatState`/`toChartOptions`/`fromChartOptions`. `spec.options = options`. `loadSpec` sets `options` from `loaded.options ?? {}`. The hook returns `options`, `setOptions`.

- [ ] **Step 1: Write the failing test** — extend `frontend/src/test/builderLoadSpec.test.tsx` (add to the existing `renderHook` test) asserting that after `loadSpec` of a v2 spec with `options.type_options.cartesian.stacked = true` and `options.legend.position = "bottom"`, `result.current.options.type_options?.cartesian?.stacked === true` and `result.current.options.legend?.position === "bottom"`.

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement** in `Builder.tsx`: replace the `format`/`setFormat` state + `toChartOptions`/`fromChartOptions`/`FormatControls` with `const [options, setOptions] = useState<ChartOptions>({});`. In the spec builder, set `options` directly (the title can be injected: `options: { ...options, title: options.title ?? title }`). In `loadSpec`, `setOptions(loaded.options ?? {})`. Render `<FormatControls options={options} setOptions={setOptions} chartType={chartType} />` in the configure card. Return `options`/`setOptions` from the hook. Remove the now-unused `FormatState` type and helpers.

- [ ] **Step 4: Run** `cd frontend && pnpm test -- builderLoadSpec && pnpm exec tsc --noEmit && pnpm lint` → PASS.

- [ ] **Step 5: Rewrite `docs/CHART_SPEC.md` options section** for v2: document the shared chrome (legend/labels/tooltip/number_format with prefix/suffix/date_format/color_scheme), the `type_options` families and their fields, the v1→v2 break, and that v1 specs are not migrated.

- [ ] **Step 6: Full slice gate.**
  - Frontend: `cd frontend && pnpm exec tsc --noEmit && pnpm lint` and the suite (`pnpm test`; if the parallel runner times out on Windows, run focused files: `chartSpec chartFormat chartRenderer charts numberRenderer formatControls builderQuery builderLoadSpec semanticQueryBuilder useChartData csv chartActionsMenu dashboardCardTile`). Report which mode.
  - Backend: `cd backend && .venv/Scripts/pytest.exe && .venv/Scripts/ruff.exe check . && .venv/Scripts/mypy.exe app`.
  - Do not claim a suite passed unless you saw it pass.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/Builder.tsx docs/CHART_SPEC.md frontend/src/test/builderLoadSpec.test.tsx
git commit -m "feat(builder): v2 ChartOptions state + wire type-aware FormatControls; docs (Slice A2)"
```

---

## Self-Review (completed during planning)

**Spec coverage** — every A2 spec item maps to a task:
- Shared chrome (color_scheme/legend type+margin+sort/number prefix+suffix/date_format/labels/tooltip) → Task 1 (schema) + Task 3 (types) + Task 4 (renderer) + Task 10 (controls).
- `type_options` family models + validation → Task 2 (schema) + Task 3 (types).
- Renderer per-family behaviour → cartesian Task 5, pie Task 6, gauge Task 7, funnel/radar/treemap Task 8, number Task 9.
- Type-aware FormatControls → Task 10; Builder v2 state + wiring → Task 11.
- Fresh-start / version "2" / no migration → Task 1 (bump + remove flat fields), fixture rewrite Task 1, downstream test fixes Task 2 Step 5.
- Docs (CHART_SPEC v2) → Task 11 Step 5.
- Dropped Superset items (D3 string, stream graph, color-by-axis, BigNumber trendline, table conditional formatting) → not in any task (correctly out of scope).

**Type consistency** — family field names match between Task 2 (backend) and Task 3 (TS mirror); the renderer tasks (5–9) read `options.type_options?.<family>` exactly as named; `FAMILY_FOR_TYPE` (Task 10) keys the same family names; the Builder (Task 11) stores `ChartOptions` and feeds `setOptions` to `FormatControls` whose signature is defined in Task 10.

**Placeholder scan** — renderer tasks give concrete ECharts mapping code; no "TBD"/"handle edge cases". Task 10's family panels reference the explicit option lists from the spec. (Task 10 Step 4 corrected to NOT touch Builder — the swap is Task 11, avoiding a contradiction.)
