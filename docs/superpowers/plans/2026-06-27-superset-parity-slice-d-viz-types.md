# Slice D — Heatmap + Sankey viz types Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `heatmap` and `sankey` as first-class grounded chart types — builder, renderer, saved charts, dashboard tiles — with full dashboard interactivity (cross-filter on click + 2-dimension-aware drill).

**Architecture:** Both types are two-dimension × one-measure visualizations. They reuse the existing encoding (`encoding.x` = dim 1, `encoding.breakdown[0]` = dim 2, `series[0].field` = measure) and the existing structured `/semantic/query` data path — no new encoding channels, no SQL. They are pure ECharts options added as branches in the shared `buildEChartsOption`. The single cross-filter overlay widens from `SemanticFilter | null` to `SemanticFilter[]` so a heatmap cell can emit two filters (x AND y).

**Tech Stack:** Python 3.12 / Pydantic v2 (backend `ChartSpec`), React + TypeScript + Vite, ECharts (`heatmap`/`sankey` series + `visualMap`), Vitest/RTL, pytest.

## Global Constraints

- **Golden rule #1 (no hardcoded config):** this slice adds **no** new settings/env. Do not introduce any.
- **Golden rule #3 (grounded):** charts are display layers over the existing structured semantic query. No raw SQL, no new physical-table access. Cross-filter/drill reuse the governed `SemanticFilter` / semantic-query paths only.
- **Golden rule #5 (done = tested + typed + documented):** every task ends green on `cd backend && .venv/Scripts/python.exe -m pytest && .venv/Scripts/ruff.exe check . && .venv/Scripts/mypy.exe app` (run pytest/ruff/mypy **from `backend/`**) and `cd frontend && pnpm exec tsc --noEmit && pnpm lint && pnpm test`.
- **`CHART_SPEC_VERSION` stays `"2"`** — these additions are backward-compatible; do not bump it.
- **Encoding contract:** dim 1 → `encoding.x`; dim 2 → `encoding.breakdown[0]`; measure → `encoding.series[0].field`; `query.dimensions = [dim1, dim2]`, `query.metric_refs = [measure]`.
- **Toolchain note:** backend pytest is CWD-sensitive — always run it from `backend/` (`cd backend && .venv/Scripts/python.exe -m pytest tests/...`). Frontend commands run from `frontend/`.

---

## File structure

**Backend**
- Modify `backend/app/schemas/chart.py` — `ChartType` += `heatmap`/`sankey`; new `HeatmapOptions`, `SankeyOptions`; `TypeOptions` fields; a `ChartSpec` validator for the 2-dim shape.
- Modify `backend/tests/test_chart_spec.py` — round-trip + validation tests.
- Modify `docs/CHART_SPEC.md` — document both types + their options.

**Frontend types**
- Modify `frontend/src/types/api.ts` — `ChartType`, `HeatmapOptions`, `SankeyOptions`, `TypeOptions`, and a shared `SelectionPair`.

**Frontend renderer**
- Modify `frontend/src/components/chart/ChartRenderer.tsx` — register `HeatmapChart`/`SankeyChart`/`VisualMapComponent`; add `buildHeatmapOption`/`buildSankeyOption`; generalize the click contract to `onSelectPoints(pairs)`.
- Modify `frontend/src/test/chartRenderer.test.ts` — heatmap + sankey build tests.

**Frontend builder**
- Modify `frontend/src/components/chart/SemanticQueryBuilder.tsx` — add both to `CHART_TYPES`; contextual dimension labels + a 2-dim hint.

**Frontend cross-filter (widen to list)**
- Modify `frontend/src/pages/DashboardDetail.tsx`, `frontend/src/components/dashboard/DashboardGrid.tsx`, `frontend/src/components/dashboard/DashboardCardTile.tsx`.
- Modify `frontend/src/test/dashboardCardTile.test.tsx`, `frontend/src/test/dashboardDetailFilters.test.tsx`.
- Modify `docs/DASHBOARDS.md` — cross-filter note for the new types.

**Frontend drill (2-dim aware)**
- Modify `frontend/src/components/chart/DrillByModal.tsx`, `frontend/src/components/chart/DrillToDetailModal.tsx`.
- Modify `frontend/src/test/drillByModal.test.tsx`, `frontend/src/test/drillToDetailModal.test.tsx`.

---

## Task 1: Backend — heatmap + sankey ChartSpec types, options, validator

**Files:**
- Modify: `backend/app/schemas/chart.py`
- Test: `backend/tests/test_chart_spec.py`
- Modify: `docs/CHART_SPEC.md`

**Interfaces:**
- Consumes: existing `ChartType`, `TypeOptions`, `HexColor`, `ChartSpec`, `ChartEncoding`.
- Produces: `ChartType` literals `"heatmap"`/`"sankey"`; `HeatmapOptions`, `SankeyOptions` (Pydantic models); `TypeOptions.heatmap`, `TypeOptions.sankey`; validator rejecting heatmap/sankey without `x` + non-empty `breakdown` + exactly one series.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_chart_spec.py`:

```python
def _heatmap_raw(series: list | None = None, breakdown: list | None = None) -> dict:
    return {
        "type": "heatmap",
        "query": {"metric_refs": ["sales.total"], "dimensions": ["sales.region", "sales.month"]},
        "encoding": {
            "x": "sales.region",
            "series": series if series is not None else [{"field": "sales.total"}],
            "breakdown": breakdown if breakdown is not None else ["sales.month"],
        },
        "options": {"type_options": {"heatmap": {"show_values": True, "max_color": "#ef4444"}}},
    }


def test_heatmap_spec_round_trips() -> None:
    spec = ChartSpec.model_validate(_heatmap_raw())
    assert spec.type == "heatmap"
    assert spec.encoding.breakdown == ["sales.month"]
    assert spec.options.type_options is not None
    assert spec.options.type_options.heatmap is not None
    assert spec.options.type_options.heatmap.show_values is True


def test_sankey_spec_round_trips() -> None:
    spec = ChartSpec.model_validate(
        {
            "type": "sankey",
            "query": {"metric_refs": ["sales.total"], "dimensions": ["sales.region", "sales.product"]},
            "encoding": {
                "x": "sales.region",
                "series": [{"field": "sales.total"}],
                "breakdown": ["sales.product"],
            },
            "options": {"type_options": {"sankey": {"orient": "vertical", "node_align": "left"}}},
        }
    )
    assert spec.type == "sankey"
    assert spec.options.type_options.sankey.orient == "vertical"


def test_matrix_chart_requires_breakdown() -> None:
    with pytest.raises(ValidationError, match="requires a second dimension"):
        ChartSpec.model_validate(_heatmap_raw(breakdown=[]))


def test_matrix_chart_requires_single_series() -> None:
    with pytest.raises(ValidationError, match="exactly one series"):
        ChartSpec.model_validate(
            _heatmap_raw(series=[{"field": "sales.total"}, {"field": "sales.count"}])
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_chart_spec.py -q`
Expected: FAIL — `heatmap` not a valid `ChartType` (ValidationError on input), and the new validator does not exist yet.

- [ ] **Step 3: Add the two types**

In `backend/app/schemas/chart.py`, extend the `ChartType` literal (add the two entries before `"table"`), and update the docstring comment above it to mention them:

```python
ChartType = Literal[
    "bar",
    "hbar",
    "line",
    "area",
    "combo",
    "pie",
    "donut",
    "scatter",
    "funnel",
    "treemap",
    "radar",
    "gauge",
    "heatmap",
    "sankey",
    "table",
    "number",
]
```

- [ ] **Step 4: Add the two option models**

In `backend/app/schemas/chart.py`, after `TreemapOptions` (before `NumberOptions`):

```python
class HeatmapOptions(BaseModel):
    """Per-chart-family display options for heatmap (a density matrix).

    The measure (``series[0]``) is mapped to cell colour via an ECharts ``visualMap``
    over the x (``encoding.x``) × y (``encoding.breakdown[0]``) grid.
    """

    show_values: bool = False
    min_color: HexColor | None = None
    max_color: HexColor | None = None
    # Manual visualMap bounds; the renderer auto-derives from the data when unset.
    value_min: float | None = None
    value_max: float | None = None
    show_visual_map: bool = True
    cell_border: bool = False


class SankeyOptions(BaseModel):
    """Per-chart-family display options for sankey (a flow diagram).

    Links flow from the x (``encoding.x``) value to the y (``encoding.breakdown[0]``)
    value, weighted by the measure (``series[0]``).
    """

    orient: Literal["horizontal", "vertical"] = "horizontal"
    node_align: Literal["left", "right", "justify"] = "justify"
    node_width: int | None = Field(default=None, ge=1, le=100)
    node_gap: int | None = Field(default=None, ge=1, le=100)
    link_color: Literal["source", "target", "gradient"] = "gradient"
    show_labels: bool = True
```

- [ ] **Step 5: Wire them into `TypeOptions`**

In `TypeOptions`, add the two fields (after `treemap`):

```python
    treemap: TreemapOptions | None = None
    heatmap: HeatmapOptions | None = None
    sankey: SankeyOptions | None = None
    number: NumberOptions | None = None
```

- [ ] **Step 6: Add the 2-dimension validator**

In `ChartSpec`, after `_require_x_for_axis_charts`:

```python
    @model_validator(mode="after")
    def _require_two_dims_for_matrix_charts(self) -> ChartSpec:
        # heatmap/sankey are 2-dimension × 1-measure: x (dim 1), breakdown[0] (dim 2),
        # and exactly one series (the measure mapped to colour / flow weight).
        if self.type in ("heatmap", "sankey"):
            if self.encoding.x is None:
                raise ValueError(f"chart type '{self.type}' requires encoding.x")
            if not self.encoding.breakdown:
                raise ValueError(
                    f"chart type '{self.type}' requires a second dimension in encoding.breakdown"
                )
            if len(self.encoding.series) != 1:
                raise ValueError(
                    f"chart type '{self.type}' requires exactly one series (the measure)"
                )
        return self
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_chart_spec.py -q`
Expected: PASS (all new tests green; existing round-trip tests still green).

- [ ] **Step 8: Document the types**

In `docs/CHART_SPEC.md`, add a subsection under the chart-types listing:

```markdown
### heatmap / sankey (2-dimension × 1-measure)

Both read **two governed dimensions and one measure**: dimension 1 → `encoding.x`,
dimension 2 → `encoding.breakdown[0]`, measure → `encoding.series[0].field`
(`query.dimensions = [dim1, dim2]`, `query.metric_refs = [measure]`). The spec
validator rejects either type without `x`, without a `breakdown` entry, or with
more than one series.

- **heatmap** — a density matrix; the measure colours each x×y cell via a `visualMap`.
  Options (`type_options.heatmap`): `show_values`, `min_color`/`max_color`,
  `value_min`/`value_max` (manual scale), `show_visual_map`, `cell_border`.
- **sankey** — a flow diagram; links go from each x value to each y value weighted by
  the measure. Options (`type_options.sankey`): `orient`, `node_align`, `node_width`,
  `node_gap`, `link_color`, `show_labels`.
```

- [ ] **Step 9: Run the full backend gate**

Run: `cd backend && .venv/Scripts/python.exe -m pytest -q && .venv/Scripts/ruff.exe check . && .venv/Scripts/mypy.exe app`
Expected: all pass.

- [ ] **Step 10: Commit**

```bash
git add backend/app/schemas/chart.py backend/tests/test_chart_spec.py docs/CHART_SPEC.md
git commit -m "feat(chart): heatmap + sankey ChartSpec types, options, and 2-dim validator (Slice D)"
```

---

## Task 2: Frontend — heatmap renderer + types

**Files:**
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/src/components/chart/ChartRenderer.tsx`
- Test: `frontend/src/test/chartRenderer.test.ts`

**Interfaces:**
- Consumes: `buildEChartsOption(spec: ChartSpec, data: QueryResponse, theme?: ChartTheme): EChartsOption` (exported), `formatChartValue`, `readChartTheme`.
- Produces: `"heatmap"` in TS `ChartType`; `HeatmapOptions` interface + `TypeOptions.heatmap`; a `heatmap` branch in `buildEChartsOption` producing `{ series: [{ type: "heatmap", … }], visualMap, xAxis, yAxis }`.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/test/chartRenderer.test.ts`:

```ts
describe("buildEChartsOption — heatmap", () => {
  const heatmapSpec: ChartSpec = {
    version: "2",
    type: "heatmap",
    query: { metric_refs: ["sales.total"], dimensions: ["sales.region", "sales.month"] },
    encoding: {
      x: "sales.region",
      series: [{ field: "sales.total" }],
      breakdown: ["sales.month"],
    },
    options: { type_options: { heatmap: { show_values: true } } },
  };
  const heatmapData: QueryResponse = {
    columns: ["sales.region", "sales.month", "sales.total"],
    rows: [
      ["West", "Jan", 10],
      ["West", "Feb", 20],
      ["East", "Jan", 5],
    ],
    row_count: 3,
  };

  it("maps the two dimensions to axes and the measure to visualMap data", () => {
    const option = buildEChartsOption(heatmapSpec, heatmapData) as Record<string, any>;
    expect(option.series[0].type).toBe("heatmap");
    // Distinct x categories and y categories become the two axes.
    expect(option.xAxis.data).toEqual(["West", "East"]);
    expect(option.yAxis.data).toEqual(["Jan", "Feb"]);
    // Each datum is [xIndex, yIndex, measure].
    expect(option.series[0].data).toContainEqual([0, 0, 10]);
    expect(option.series[0].data).toContainEqual([1, 0, 5]);
    expect(option.visualMap.max).toBe(20);
    expect(option.series[0].label.show).toBe(true);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && pnpm exec vitest run src/test/chartRenderer.test.ts -t heatmap`
Expected: FAIL — `"heatmap"` is not assignable to `ChartType` (tsc) and the branch throws/returns wrong shape.

- [ ] **Step 3: Add the TS type mirror**

In `frontend/src/types/api.ts`, add `"heatmap"` to the `ChartType` union (next to the other types), add the interface (after `TreemapOptions`):

```ts
export interface HeatmapOptions {
  show_values?: boolean;
  min_color?: string | null;
  max_color?: string | null;
  value_min?: number | null;
  value_max?: number | null;
  show_visual_map?: boolean;
  cell_border?: boolean;
}
```

and add to `TypeOptions`:

```ts
  heatmap?: HeatmapOptions | null;
```

- [ ] **Step 4: Register the ECharts modules**

In `frontend/src/components/chart/ChartRenderer.tsx`, add `HeatmapChart` to the `echarts/charts` import and `VisualMapComponent` to the `echarts/components` import, then add both to the `echarts.use([...])` list:

```ts
// in the echarts/charts import block:
  HeatmapChart,
// in the echarts/components import block:
  VisualMapComponent,
// in echarts.use([...]):
  HeatmapChart,
  VisualMapComponent,
```

- [ ] **Step 5: Add `buildHeatmapOption` and dispatch**

In `ChartRenderer.tsx`, add this function above `buildEChartsOption`:

```ts
/** Heatmap: x dimension × y dimension (breakdown[0]) grid, measure → cell colour. */
function buildHeatmapOption(
  spec: ChartSpec,
  data: QueryResponse,
  theme: ChartTheme
): EChartsOption {
  const h = spec.options.type_options?.heatmap ?? {};
  const xCol = spec.encoding.x as string;
  const yCol = spec.encoding.breakdown[0];
  const vCol = spec.encoding.series[0].field;
  const xIdx = data.columns.indexOf(xCol);
  const yIdx = data.columns.indexOf(yCol);
  const vIdx = data.columns.indexOf(vCol);
  if (xIdx < 0 || yIdx < 0 || vIdx < 0) {
    throw new Error("heatmap requires x, breakdown[0], and a measure present in the data");
  }
  const xs: string[] = [];
  const ys: string[] = [];
  for (const r of data.rows) {
    const xv = String(r[xIdx]);
    const yv = String(r[yIdx]);
    if (!xs.includes(xv)) xs.push(xv);
    if (!ys.includes(yv)) ys.push(yv);
  }
  const cells = data.rows.map((r) => [
    xs.indexOf(String(r[xIdx])),
    ys.indexOf(String(r[yIdx])),
    Number(r[vIdx] ?? 0) || 0,
  ]);
  const values = cells.map((c) => c[2] as number);
  const fmt = (v: number) => formatChartValue(v, spec.options.number_format);
  return {
    tooltip: { position: "top" },
    grid: { containLabel: true, left: 8, right: 8, top: 8, bottom: 8 },
    xAxis: { type: "category", data: xs, axisLabel: { color: theme.text } },
    yAxis: { type: "category", data: ys, axisLabel: { color: theme.text } },
    visualMap: {
      min: h.value_min ?? Math.min(0, ...values),
      max: h.value_max ?? Math.max(0, ...values),
      calculable: true,
      orient: "horizontal",
      left: "center",
      bottom: 0,
      show: h.show_visual_map !== false,
      inRange: { color: [h.min_color ?? "#e0f2fe", h.max_color ?? "#0369a1"] },
      textStyle: { color: theme.text },
    },
    series: [
      {
        type: "heatmap",
        data: cells,
        label: { show: h.show_values === true, formatter: (p: any) => fmt(Number(p.value[2])) },
        itemStyle: h.cell_border ? { borderColor: theme.axisLine, borderWidth: 1 } : undefined,
      },
    ],
  } as EChartsOption;
}
```

Then in `buildEChartsOption`, add the dispatch near the top (before the cartesian/other branches; mirror where `if (spec.type === "scatter")` etc. live):

```ts
  if (spec.type === "heatmap") {
    return buildHeatmapOption(spec, data, theme);
  }
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd frontend && pnpm exec vitest run src/test/chartRenderer.test.ts -t heatmap`
Expected: PASS.

- [ ] **Step 7: Run tsc + lint**

Run: `cd frontend && pnpm exec tsc --noEmit && pnpm lint`
Expected: pass (0 errors).

- [ ] **Step 8: Commit**

```bash
git add frontend/src/types/api.ts frontend/src/components/chart/ChartRenderer.tsx frontend/src/test/chartRenderer.test.ts
git commit -m "feat(chart): heatmap renderer (visualMap over x×y grid) (Slice D)"
```

---

## Task 3: Frontend — sankey renderer + types

**Files:**
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/src/components/chart/ChartRenderer.tsx`
- Test: `frontend/src/test/chartRenderer.test.ts`

**Interfaces:**
- Consumes: `buildEChartsOption`, `ChartTheme`.
- Produces: `"sankey"` in TS `ChartType`; `SankeyOptions` + `TypeOptions.sankey`; a `sankey` branch producing `{ series: [{ type: "sankey", data: nodes, links }] }`.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/test/chartRenderer.test.ts`:

```ts
describe("buildEChartsOption — sankey", () => {
  const sankeySpec: ChartSpec = {
    version: "2",
    type: "sankey",
    query: { metric_refs: ["sales.total"], dimensions: ["sales.region", "sales.product"] },
    encoding: {
      x: "sales.region",
      series: [{ field: "sales.total" }],
      breakdown: ["sales.product"],
    },
    options: { type_options: { sankey: { orient: "vertical" } } },
  };
  const sankeyData: QueryResponse = {
    columns: ["sales.region", "sales.product", "sales.total"],
    rows: [
      ["West", "Widget", 10],
      ["East", "Widget", 5],
    ],
    row_count: 2,
  };

  it("builds nodes from both dimensions and weighted links", () => {
    const option = buildEChartsOption(sankeySpec, sankeyData) as Record<string, any>;
    expect(option.series[0].type).toBe("sankey");
    expect(option.series[0].orient).toBe("vertical");
    const nodeNames = option.series[0].data.map((n: any) => n.name);
    expect(nodeNames).toContain("West");
    expect(nodeNames).toContain("Widget");
    expect(option.series[0].links).toContainEqual({ source: "West", target: "Widget", value: 10 });
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && pnpm exec vitest run src/test/chartRenderer.test.ts -t sankey`
Expected: FAIL — `"sankey"` not in `ChartType`, no branch.

- [ ] **Step 3: Add the TS type mirror**

In `frontend/src/types/api.ts`, add `"sankey"` to `ChartType`, add the interface (after `HeatmapOptions`):

```ts
export interface SankeyOptions {
  orient?: "horizontal" | "vertical";
  node_align?: "left" | "right" | "justify";
  node_width?: number | null;
  node_gap?: number | null;
  link_color?: "source" | "target" | "gradient";
  show_labels?: boolean;
}
```

and add to `TypeOptions`:

```ts
  sankey?: SankeyOptions | null;
```

- [ ] **Step 4: Register the ECharts module**

In `ChartRenderer.tsx`, add `SankeyChart` to the `echarts/charts` import and to `echarts.use([...])`.

- [ ] **Step 5: Add `buildSankeyOption` and dispatch**

Add above `buildEChartsOption`:

```ts
/** Sankey: links from each x value to each y value (breakdown[0]), weighted by the measure. */
function buildSankeyOption(
  spec: ChartSpec,
  data: QueryResponse,
  theme: ChartTheme
): EChartsOption {
  const s = spec.options.type_options?.sankey ?? {};
  const xIdx = data.columns.indexOf(spec.encoding.x as string);
  const yIdx = data.columns.indexOf(spec.encoding.breakdown[0]);
  const vIdx = data.columns.indexOf(spec.encoding.series[0].field);
  if (xIdx < 0 || yIdx < 0 || vIdx < 0) {
    throw new Error("sankey requires x, breakdown[0], and a measure present in the data");
  }
  // Disjoint node id namespaces: a target that shares an x value gets a suffix so links
  // stay acyclic; the label strips the suffix for display.
  const names = new Set<string>();
  const nodes: { name: string }[] = [];
  const addNode = (name: string) => {
    if (!names.has(name)) {
      names.add(name);
      nodes.push({ name });
    }
  };
  const links = data.rows.map((r) => {
    const src = String(r[xIdx]);
    let tgt = String(r[yIdx]);
    if (src === tgt) tgt = `${tgt}​`; // zero-width suffix to break a self-cycle
    addNode(src);
    addNode(tgt);
    return { source: src, target: tgt, value: Number(r[vIdx] ?? 0) || 0 };
  });
  return {
    tooltip: { trigger: "item" },
    series: [
      {
        type: "sankey",
        orient: s.orient ?? "horizontal",
        nodeAlign: s.node_align ?? "justify",
        nodeWidth: s.node_width ?? 20,
        nodeGap: s.node_gap ?? 8,
        data: nodes,
        links,
        label: { show: s.show_labels !== false, color: theme.text,
          formatter: (p: any) => String(p.name).replace(/​/g, "") },
        lineStyle: { color: s.link_color ?? "gradient", opacity: 0.4 },
      },
    ],
  } as EChartsOption;
}
```

Add the dispatch in `buildEChartsOption`:

```ts
  if (spec.type === "sankey") {
    return buildSankeyOption(spec, data, theme);
  }
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd frontend && pnpm exec vitest run src/test/chartRenderer.test.ts -t sankey`
Expected: PASS.

- [ ] **Step 7: Run tsc + lint + full renderer tests**

Run: `cd frontend && pnpm exec tsc --noEmit && pnpm lint && pnpm exec vitest run src/test/chartRenderer.test.ts`
Expected: pass.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/types/api.ts frontend/src/components/chart/ChartRenderer.tsx frontend/src/test/chartRenderer.test.ts
git commit -m "feat(chart): sankey renderer (weighted flows between two dimensions) (Slice D)"
```

---

## Task 4: Builder — expose heatmap + sankey

**Files:**
- Modify: `frontend/src/components/chart/SemanticQueryBuilder.tsx`

**Interfaces:**
- Consumes: `CHART_TYPES: ChartType[]`, the existing multi-dimension drag flow, `s.chartType`.
- Produces: heatmap/sankey selectable; a hint shown for these two types.

- [ ] **Step 1: Add both to the type list**

In `SemanticQueryBuilder.tsx`, add `"heatmap"` and `"sankey"` to `CHART_TYPES` (after `"gauge"`, before `"table"`):

```ts
  "gauge",
  "heatmap",
  "sankey",
  "table",
```

- [ ] **Step 2: Add the 2-dimension hint**

Find the chart-type `<Select>` (around line 399, `onChange={(e) => s.setChartType(e.target.value as ChartType)}`). Immediately after that `<Select>`'s closing tag, add a contextual hint:

```tsx
{(s.chartType === "heatmap" || s.chartType === "sankey") && (
  <p className="mt-1 text-xs text-muted-foreground">
    {s.chartType === "heatmap"
      ? "Add two dimensions (X, Y) and one measure — the measure colours each cell."
      : "Add two dimensions (Source, Target) and one measure — the measure is the flow weight."}
  </p>
)}
```

- [ ] **Step 3: Run tsc + lint + existing builder tests**

Run: `cd frontend && pnpm exec tsc --noEmit && pnpm lint && pnpm exec vitest run src/test/builderLoadSpec.test.tsx`
Expected: pass (no regressions; the new types are additive).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/chart/SemanticQueryBuilder.tsx
git commit -m "feat(builder): expose heatmap + sankey types with a 2-dimension hint (Slice D)"
```

---

## Task 5: Cross-filter — widen the overlay to a list

This is a behaviour-preserving refactor: it generalizes the single `SemanticFilter | null`
overlay to `SemanticFilter[]` and the click callback to emit `SelectionPair[]`, without
changing what existing charts do. Heatmap/sankey emission comes in Task 6.

**Files:**
- Modify: `frontend/src/types/api.ts` (add `SelectionPair`)
- Modify: `frontend/src/components/chart/ChartRenderer.tsx` (`onSelectCategory` → `onSelectPoints`)
- Modify: `frontend/src/pages/DashboardDetail.tsx`
- Modify: `frontend/src/components/dashboard/DashboardGrid.tsx`
- Modify: `frontend/src/components/dashboard/DashboardCardTile.tsx`
- Test: `frontend/src/test/dashboardCardTile.test.tsx`

**Interfaces:**
- Produces: `SelectionPair = { member: string; value: string }`; `ChartRenderer` prop `onSelectPoints?: (pairs: SelectionPair[]) => void`; `crossFilter: SemanticFilter[]` everywhere it was `SemanticFilter | null`; `onCrossFilter?: (pairs: SelectionPair[]) => void`.

- [ ] **Step 1: Update the failing test first**

In `frontend/src/test/dashboardCardTile.test.tsx`: change the `ChartRenderer` mock to expose `onSelectPoints`, and update the cross-filter expectations to the list shape. Replace the mock's `onSelectCategory` block and the two relevant tests:

```tsx
// In the vi.mock("@/components/chart/ChartRenderer", …) factory, replace onSelectCategory:
  ChartRenderer: ({
    title,
    onSelectPoints,
  }: {
    title?: string;
    onSelectPoints?: (pairs: { member: string; value: string }[]) => void;
  }) => (
    <div role="img" aria-label={title ?? "chart"} data-testid="chart-renderer">
      {onSelectPoints && (
        <button type="button" onClick={() => onSelectPoints([{ member: "regional_sales.region", value: "west" }])}>
          point
        </button>
      )}
    </div>
  ),
```

```tsx
// "cross-filters from a clicked category" test:
  it("cross-filters from a clicked point using member+value pairs", () => {
    const onCrossFilter = vi.fn();
    render(
      <DashboardCardTile tile={tile} dashboardId="dash-1" editing={false} onCrossFilter={onCrossFilter} />
    );
    fireEvent.click(screen.getByRole("button", { name: "point" }));
    expect(onCrossFilter).toHaveBeenCalledWith([{ member: "regional_sales.region", value: "west" }]);
  });
```

```tsx
// "applies a cross-filter overlay when cube matches" test — pass an array now:
  it("applies a cross-filter overlay when cube matches", () => {
    render(
      <DashboardCardTile tile={tile} dashboardId="dash-1" editing={false} crossFilter={[crossFilterSameCube]} />
    );
    expect(mockUseChartData).toHaveBeenCalledWith(spec, [crossFilterSameCube], undefined);
    expect(screen.getByText(/filtered/i)).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && pnpm exec vitest run src/test/dashboardCardTile.test.tsx`
Expected: FAIL — props are still the old single-value shape.

- [ ] **Step 3: Add `SelectionPair` and update the renderer prop**

In `frontend/src/types/api.ts` add:

```ts
/** One (governed member, value) pair emitted by a chart click for cross-filtering. */
export interface SelectionPair {
  member: string;
  value: string;
}
```

In `ChartRenderer.tsx`: import `SelectionPair`; rename the prop and generalize the emitter. Replace the `onSelectCategory` prop, the `onSelectRef`, and the click handler:

```ts
// prop (replace onSelectCategory):
  onSelectPoints?: (pairs: SelectionPair[]) => void;
```

```ts
// ref + effect (replace the onSelectCategory ref):
  const onSelectRef = useRef(onSelectPoints);
  useEffect(() => {
    onSelectRef.current = onSelectPoints;
  });
```

```ts
// destructure in the component signature: { spec, data, title, className = "", onSelectPoints }
```

The click listener is attached once (in the mount effect) but must read the **current**
spec. Keep the mount effect's deps as `[isEcharts]` (do NOT add `spec` — that would
dispose/re-init the instance on every data change). Instead add a `specRef` kept current,
alongside the existing `onSelectRef`:

```ts
  const specRef = useRef(spec);
  useEffect(() => {
    specRef.current = spec;
  });
```

Replace the click handler body inside the mount effect:

```ts
    instance.on("click", (params) => {
      const pairs = selectionPairsFromClick(specRef.current, params as Record<string, unknown>);
      if (pairs.length > 0) onSelectRef.current?.(pairs);
    });
```

Add this helper above the component (it handles the existing category charts now; Task 6 extends it):

```ts
/** Map an ECharts click to cross-filter pairs. Category charts emit one pair on `x`. */
function selectionPairsFromClick(
  spec: ChartSpec,
  params: Record<string, unknown>
): SelectionPair[] {
  const name = params.name as string | undefined;
  if (name && spec.encoding.x) {
    return [{ member: spec.encoding.x, value: String(name) }];
  }
  return [];
}
```

- [ ] **Step 4: Widen `DashboardCardTile`**

In `DashboardCardTile.tsx`:
- Change both `crossFilter?: SemanticFilter | null` / `crossFilter: SemanticFilter | null` prop types to `crossFilter?: SemanticFilter[]` / `crossFilter: SemanticFilter[]`, and default `crossFilter = []` in `DashboardCardTile`.
- Change both `onCrossFilter?: (member: string, value: string) => void` to `onCrossFilter?: (pairs: SelectionPair[]) => void` (import `SelectionPair`).
- In `ChartTileBody`, replace the single-overlay logic with list-merge and drop the `crossDimension`/`onSelectCategory` mapping:

```ts
  const { filters: resolved, dateRanges } = resolveTileFilters(filters, selections, tile);
  const tileCube = cubeOf((spec?.query.metric_refs ?? [])[0]);
  const crossMatching = crossFilter.filter((cf) => !!tileCube && cubeOf(cf.member) === tileCube);
  const appliedFilters: SemanticFilter[] = [...resolved, ...crossMatching];
  const hasOverride = Object.keys(dateRanges).length > 0;
```

(delete the `crossApplies` / `crossDimension` / `onSelectCategory` consts.)

- Update the `<ChartRenderer>` prop:

```tsx
          <ChartRenderer
            ref={chartHandle}
            spec={spec}
            data={data}
            title={title}
            className="h-64"
            onSelectPoints={editing ? undefined : onCrossFilter}
          />
```

- [ ] **Step 5: Widen `DashboardGrid`**

In `DashboardGrid.tsx`: change `crossFilter: SemanticFilter | null` → `crossFilter: SemanticFilter[]` and `onCrossFilter?: (member: string, value: string) => void` → `onCrossFilter?: (pairs: SelectionPair[]) => void` (import `SelectionPair`). Pass-through is unchanged.

- [ ] **Step 6: Widen `DashboardDetail`**

In `DashboardDetail.tsx`:
- Change state: `const [crossFilter, setCrossFilter] = useState<SemanticFilter[]>([]);`
- Replace `handleCrossFilter`:

```ts
  function handleCrossFilter(pairs: SelectionPair[]) {
    setCrossFilter(pairs.map((p) => ({ member: p.member, operator: "equals", values: [p.value] })));
  }
```

- In `onClearAll` and the seed-reset block, replace `setCrossFilter(null)` with `setCrossFilter([])` (two sites).
- Update the `<DashboardGrid>` prop: `crossFilter={editing ? [] : crossFilter}` (was `null`).
- Import `SelectionPair` in the type import from `@/types/api`.

- [ ] **Step 7: Run the test + tsc + lint**

Run: `cd frontend && pnpm exec tsc --noEmit && pnpm lint && pnpm exec vitest run src/test/dashboardCardTile.test.tsx src/test/dashboardDetailFilters.test.tsx`
Expected: PASS. (If `dashboardDetailFilters.test.tsx` references `crossFilter` as a single value or `onSelectCategory`, update those references to the array / `onSelectPoints` shape in the same step.)

- [ ] **Step 8: Run the whole frontend suite**

Run: `cd frontend && pnpm test`
Expected: all pass (the refactor preserves existing behaviour).

- [ ] **Step 9: Commit**

```bash
git add frontend/src/types/api.ts frontend/src/components/chart/ChartRenderer.tsx frontend/src/pages/DashboardDetail.tsx frontend/src/components/dashboard/DashboardGrid.tsx frontend/src/components/dashboard/DashboardCardTile.tsx frontend/src/test/dashboardCardTile.test.tsx frontend/src/test/dashboardDetailFilters.test.tsx
git commit -m "refactor(dashboard): widen cross-filter overlay to a SemanticFilter list (Slice D)"
```

---

## Task 6: Cross-filter emission for heatmap cell (x+y) and sankey node

**Files:**
- Modify: `frontend/src/components/chart/ChartRenderer.tsx` (`selectionPairsFromClick`)
- Test: `frontend/src/test/chartRenderer.test.ts`
- Modify: `docs/DASHBOARDS.md`

**Interfaces:**
- Consumes: `selectionPairsFromClick(spec, params)` from Task 5.
- Produces: heatmap cell → two pairs (x, y); sankey node → one pair (the node's dimension).

- [ ] **Step 1: Write the failing test**

`selectionPairsFromClick` is module-private. Export it for testing — add `export` to its declaration in `ChartRenderer.tsx` — then append to `frontend/src/test/chartRenderer.test.ts`:

```ts
import { selectionPairsFromClick } from "@/components/chart/ChartRenderer";

describe("selectionPairsFromClick", () => {
  const heatmapSpec: ChartSpec = {
    version: "2", type: "heatmap",
    query: { metric_refs: ["sales.total"], dimensions: ["sales.region", "sales.month"] },
    encoding: { x: "sales.region", series: [{ field: "sales.total" }], breakdown: ["sales.month"] },
    options: {},
  };
  const sankeySpec: ChartSpec = { ...heatmapSpec, type: "sankey",
    encoding: { x: "sales.region", series: [{ field: "sales.total" }], breakdown: ["sales.product"] } };

  it("emits both axes for a heatmap cell", () => {
    // buildHeatmapOption emits each datum as { value:[xIdx,yIdx,measure], $xCat, $yCat },
    // and ECharts passes that object back as params.data on click.
    const pairs = selectionPairsFromClick(heatmapSpec, {
      seriesType: "heatmap",
      data: { value: [0, 1, 10], $xCat: "West", $yCat: "Feb" },
    } as any);
    expect(pairs).toEqual([
      { member: "sales.region", value: "West" },
      { member: "sales.month", value: "Feb" },
    ]);
  });

  it("emits one pair for a sankey node", () => {
    const pairs = selectionPairsFromClick(sankeySpec, {
      seriesType: "sankey", dataType: "node", name: "Widget",
    } as any);
    expect(pairs).toEqual([{ member: "sales.product", value: "Widget" }]);
  });

  it("ignores a sankey edge click", () => {
    expect(selectionPairsFromClick(sankeySpec, { seriesType: "sankey", dataType: "edge" } as any)).toEqual([]);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && pnpm exec vitest run src/test/chartRenderer.test.ts -t selectionPairsFromClick`
Expected: FAIL — heatmap/sankey branches not handled.

- [ ] **Step 3: Provide resolved category labels on heatmap clicks**

ECharts heatmap click `params.value` is `[xIndex, yIndex, measure]`, not the labels. The simplest robust source is the axis arrays the option already carries. In `buildHeatmapOption`, stash the resolved categories on each datum so a click can read them back — change the `cells` mapping to richer data objects:

```ts
  const cells = data.rows.map((r) => ({
    value: [xs.indexOf(String(r[xIdx])), ys.indexOf(String(r[yIdx])), Number(r[vIdx] ?? 0) || 0],
    $xCat: String(r[xIdx]),
    $yCat: String(r[yIdx]),
  }));
```

(ECharts accepts `{ value, …custom }` data items and passes the custom keys through on click as `params.data`.)

- [ ] **Step 4: Extend `selectionPairsFromClick`**

Replace the helper body in `ChartRenderer.tsx`:

```ts
/** Map an ECharts click to cross-filter pairs. */
export function selectionPairsFromClick(
  spec: ChartSpec,
  params: Record<string, unknown>
): SelectionPair[] {
  if (spec.type === "heatmap") {
    const datum = params.data as { $xCat?: string; $yCat?: string } | undefined;
    const yMember = spec.encoding.breakdown[0];
    if (datum?.$xCat != null && datum?.$yCat != null && spec.encoding.x && yMember) {
      return [
        { member: spec.encoding.x, value: String(datum.$xCat) },
        { member: yMember, value: String(datum.$yCat) },
      ];
    }
    return [];
  }
  if (spec.type === "sankey") {
    // Only node clicks cross-filter; nodes from the x set map to x, others to breakdown[0].
    if (params.dataType !== "node") return [];
    const name = String(params.name ?? "").replace(/​/g, "");
    const yMember = spec.encoding.breakdown[0];
    // We cannot tell from the click alone which dimension a node belongs to, so resolve by
    // membership: a value present in the x column is an x node, otherwise a y node. The
    // renderer attaches the side via the node's `$member` (set in buildSankeyOption).
    const member = (params.data as { $member?: string } | undefined)?.$member ?? yMember;
    return name ? [{ member, value: name }] : [];
  }
  const name = params.name as string | undefined;
  if (name && spec.encoding.x) {
    return [{ member: spec.encoding.x, value: String(name) }];
  }
  return [];
}
```

- [ ] **Step 5: Tag sankey nodes with their dimension**

In `buildSankeyOption`, record which member each node belongs to so a click can resolve it. Change `addNode` and the node objects:

```ts
  const nodes: { name: string; $member: string }[] = [];
  const addNode = (name: string, member: string) => {
    if (!names.has(name)) {
      names.add(name);
      nodes.push({ name, $member: member });
    }
  };
```

and in the link mapping call `addNode(src, spec.encoding.x as string)` and `addNode(tgt, spec.encoding.breakdown[0])`.

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd frontend && pnpm exec vitest run src/test/chartRenderer.test.ts -t selectionPairsFromClick`
Expected: PASS.

- [ ] **Step 7: Document the interaction**

In `docs/DASHBOARDS.md`, under the cross-filter section, add:

```markdown
Heatmap and sankey participate in cross-filtering: clicking a **heatmap cell** emits two
filters (its x value AND its y value); clicking a **sankey node** emits one filter on that
node's dimension. As with other charts, a cross-filter only applies to tiles whose cube
contains the filtered member.
```

- [ ] **Step 8: Run tsc + lint + full frontend suite**

Run: `cd frontend && pnpm exec tsc --noEmit && pnpm lint && pnpm test`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/chart/ChartRenderer.tsx frontend/src/test/chartRenderer.test.ts docs/DASHBOARDS.md
git commit -m "feat(dashboard): cross-filter from heatmap cells (x+y) and sankey nodes (Slice D)"
```

---

## Task 7: Drill — exclude both encoded dimensions for 2-dim charts

**Files:**
- Modify: `frontend/src/components/chart/DrillByModal.tsx`
- Modify: `frontend/src/components/chart/DrillToDetailModal.tsx`
- Test: `frontend/src/test/drillByModal.test.tsx`
- Test: `frontend/src/test/drillToDetailModal.test.tsx`

**Interfaces:**
- Consumes: `DrillByModal` `dimensionOptions` (re-pivot candidates), `buildDetailRequest`.
- Produces: both modals exclude `encoding.x ∪ encoding.breakdown ∪ query.dimensions` from their candidate dimensions.

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/test/drillByModal.test.tsx` (component-level — reuses the existing mocks in that file):

```tsx
it("excludes both encoded dimensions for a heatmap (x and breakdown)", () => {
  const heatmapSpec: ChartSpec = {
    type: "heatmap",
    query: { metric_refs: ["regional_sales.total_amount"], dimensions: ["regional_sales.region", "regional_sales.product"] },
    encoding: { x: "regional_sales.region", series: [{ field: "regional_sales.total_amount" }], breakdown: ["regional_sales.product"] },
  };
  render(<DrillByModal open onOpenChange={vi.fn()} spec={heatmapSpec} tileFilters={[]} data={tileData} />);
  const dim = screen.getByLabelText("Dimension");
  // Neither encoded dimension is offered as a re-pivot target.
  expect(within(dim).queryByRole("option", { name: "Region" })).not.toBeInTheDocument();
  expect(within(dim).queryByRole("option", { name: "Product" })).not.toBeInTheDocument();
});
```

Append to `frontend/src/test/drillToDetailModal.test.tsx`:

```ts
it("excludes the breakdown dimension from the detail breakdown", () => {
  const heatmapSpec: ChartSpec = {
    type: "heatmap",
    query: { metric_refs: ["regional_sales.total_amount"], dimensions: ["regional_sales.region"] },
    encoding: { x: "regional_sales.region", series: [{ field: "regional_sales.total_amount" }], breakdown: ["regional_sales.product"] },
  };
  const req = buildDetailRequest(heatmapSpec, models, null, []);
  expect(req?.dimensions).not.toContain("regional_sales.region");
  expect(req?.dimensions).not.toContain("regional_sales.product");
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && pnpm exec vitest run src/test/drillByModal.test.tsx src/test/drillToDetailModal.test.tsx`
Expected: FAIL — `Product` is still offered (drill-by only excludes `baseX`); `buildDetailRequest` only excludes `query.dimensions ∪ x`, so `product` (in breakdown, not query.dimensions in this fixture) leaks in.

- [ ] **Step 3: Exclude breakdown + query.dimensions in DrillByModal**

In `DrillByModal.tsx`, replace the `dimensionOptions` useMemo body:

```ts
  const dimensionOptions = useMemo(() => {
    const model = (models ?? []).find((m) => m.name === baseCube);
    const encoded = new Set<string>([
      ...(baseX ? [baseX] : []),
      ...(spec.encoding.breakdown ?? []),
      ...(spec.query.dimensions ?? []),
    ]);
    return (model?.dimensions ?? []).filter((d) => !encoded.has(d.name));
  }, [models, baseCube, baseX, spec.encoding.breakdown, spec.query.dimensions]);
```

- [ ] **Step 4: Exclude breakdown in buildDetailRequest**

In `DrillToDetailModal.tsx`, add the breakdown members to the `encoded` set in `buildDetailRequest`:

```ts
  const encoded = new Set<string>([
    ...(spec.query.dimensions ?? []),
    ...(spec.encoding.breakdown ?? []),
    ...(spec.encoding.x ? [spec.encoding.x] : []),
  ]);
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd frontend && pnpm exec vitest run src/test/drillByModal.test.tsx src/test/drillToDetailModal.test.tsx`
Expected: PASS.

- [ ] **Step 6: Run the full frontend gate**

Run: `cd frontend && pnpm exec tsc --noEmit && pnpm lint && pnpm test`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/chart/DrillByModal.tsx frontend/src/components/chart/DrillToDetailModal.tsx frontend/src/test/drillByModal.test.tsx frontend/src/test/drillToDetailModal.test.tsx
git commit -m "feat(chart): make drill-by / drill-to-detail exclude both encoded dims (Slice D)"
```

---

## Final verification (whole slice)

- [ ] **Backend gate:** `cd backend && .venv/Scripts/python.exe -m pytest -q && .venv/Scripts/ruff.exe check . && .venv/Scripts/mypy.exe app` — all pass.
- [ ] **Frontend gate:** `cd frontend && pnpm exec tsc --noEmit && pnpm lint && pnpm test` — all pass.
- [ ] **Manual smoke (optional):** build a heatmap and a sankey in the builder over a 2-dimension semantic query, save each, pin to a dashboard, click a heatmap cell and confirm the rest of the dashboard cross-filters on both axes; open drill-by on a heatmap and confirm neither encoded dimension is offered.
- [ ] **Spec parity:** confirm every part of `docs/superpowers/specs/2026-06-27-superset-parity-slice-d-viz-types-design.md` (parts 1–7) maps to a committed task.
- [ ] **Progress log:** append a Slice D section to `.superpowers/sdd/progress.md` summarizing the tasks and the verified gate.

---

## Self-review notes (author)

- **Spec coverage:** part 1 → Task 1; part 2 → Tasks 2–3; part 3 → Task 4; part 4 → Tasks 5–6; part 5 → Task 7; part 6 (testing) → per-task tests + final verification; part 7 (golden rules) → Global Constraints + each task's gate. No gaps.
- **Type consistency:** `SelectionPair { member; value }`, `onSelectPoints(pairs)`, `crossFilter: SemanticFilter[]`, `selectionPairsFromClick(spec, params)`, `buildHeatmapOption`/`buildSankeyOption`, `HeatmapOptions`/`SankeyOptions` used consistently across tasks.
- **Open items (from spec):** heatmap default gradient = `#e0f2fe → #0369a1` (overridable via `min_color`/`max_color`, Task 2 Step 5); sankey self-cycle/node-id collisions handled with a zero-width-space suffix stripped at label time (Task 3 Step 5), with node→dimension tagging via `$member` (Task 6 Step 5).
