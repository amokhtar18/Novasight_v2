/**
 * Unit tests for ChartRenderer's buildEChartsOption mapping function.
 *
 * Tests run in Node (no DOM needed) since we test pure data transformation.
 */

import { describe, it, expect, test } from "vitest";
import type { ChartRendererHandle } from "@/components/chart/ChartRenderer";
import { buildEChartsOption, selectionPairsFromClick } from "@/components/chart/ChartRenderer";
import type { ChartSpec, QueryResponse } from "@/types/api";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const sampleQueryResponse: QueryResponse = {
  columns: ["category", "count"],
  rows: [
    ["alpha", 10],
    ["beta", 25],
    ["gamma", 7],
  ],
  row_count: 3,
};

// A minimal data source shared by the fixtures (the renderer ignores `query`).
const countQuery: ChartSpec["query"] = {
  dataset_id: null,
  query: {
    dimensions: ["category"],
    metrics: [{ function: "count" }],
  },
};

const barSpec: ChartSpec = {
  type: "bar",
  query: countQuery,
  encoding: { x: "category", series: [{ field: "count", name: "Count" }] },
};

const pieSpec: ChartSpec = {
  type: "pie",
  query: countQuery,
  encoding: { x: "category", series: [{ field: "count", name: "Count" }] },
};

const lineSpec: ChartSpec = {
  type: "line",
  query: countQuery,
  encoding: { x: "category", series: [{ field: "count", name: "Count" }] },
};

// ---------------------------------------------------------------------------
// Bar chart
// ---------------------------------------------------------------------------

describe("buildEChartsOption — bar", () => {
  it("produces xAxis categories from the x column", () => {
    const option = buildEChartsOption(barSpec, sampleQueryResponse);
    const xAxis = option.xAxis as { data: string[] };
    expect(xAxis.data).toEqual(["alpha", "beta", "gamma"]);
  });

  it("produces one series with bar type", () => {
    const option = buildEChartsOption(barSpec, sampleQueryResponse);
    const series = option.series as Array<{ type: string; data: number[] }>;
    expect(series).toHaveLength(1);
    expect(series[0].type).toBe("bar");
    expect(series[0].data).toEqual([10, 25, 7]);
  });

  it("sets series name from spec", () => {
    const option = buildEChartsOption(barSpec, sampleQueryResponse);
    const series = option.series as Array<{ name: string }>;
    expect(series[0].name).toBe("Count");
  });
});

// ---------------------------------------------------------------------------
// Line chart
// ---------------------------------------------------------------------------

describe("buildEChartsOption — line", () => {
  it("produces series with line type", () => {
    const option = buildEChartsOption(lineSpec, sampleQueryResponse);
    const series = option.series as Array<{ type: string }>;
    expect(series[0].type).toBe("line");
  });
});

// ---------------------------------------------------------------------------
// Pie chart
// ---------------------------------------------------------------------------

describe("buildEChartsOption — pie", () => {
  it("produces a pie series with name/value pairs", () => {
    const option = buildEChartsOption(pieSpec, sampleQueryResponse);
    const series = option.series as Array<{
      type: string;
      data: Array<{ name: string; value: number }>;
    }>;
    expect(series).toHaveLength(1);
    expect(series[0].type).toBe("pie");
    expect(series[0].data).toEqual([
      { name: "alpha", value: 10 },
      { name: "beta", value: 25 },
      { name: "gamma", value: 7 },
    ]);
  });
});

// ---------------------------------------------------------------------------
// Error handling
// ---------------------------------------------------------------------------

describe("buildEChartsOption — error handling", () => {
  it("throws if the x column is not in QueryResponse", () => {
    const badSpec: ChartSpec = {
      ...barSpec,
      encoding: { ...barSpec.encoding, x: "nonexistent_column" },
    };
    expect(() => buildEChartsOption(badSpec, sampleQueryResponse)).toThrow(
      /nonexistent_column/
    );
  });

  it("throws if a series field is not in QueryResponse", () => {
    const badSpec: ChartSpec = {
      ...barSpec,
      encoding: {
        ...barSpec.encoding,
        series: [{ field: "no_such_column", name: "Missing" }],
      },
    };
    expect(() => buildEChartsOption(badSpec, sampleQueryResponse)).toThrow(
      /no_such_column/
    );
  });

  it("replaces null x values with '(null)'", () => {
    const dataWithNull: QueryResponse = {
      columns: ["category", "count"],
      rows: [[null, 5]],
      row_count: 1,
    };
    const option = buildEChartsOption(barSpec, dataWithNull);
    const xAxis = option.xAxis as { data: string[] };
    expect(xAxis.data[0]).toBe("(null)");
  });
});

// ---------------------------------------------------------------------------
// Scatter chart
// ---------------------------------------------------------------------------

describe("buildEChartsOption — scatter", () => {
  const scatterData: QueryResponse = {
    columns: ["price", "rating"],
    rows: [
      [10, 4.2],
      [25, 3.8],
    ],
    row_count: 2,
  };
  const scatterSpec: ChartSpec = {
    type: "scatter",
    query: countQuery,
    encoding: { x: "price", series: [{ field: "rating", name: "Rating" }] },
  };

  it("uses a value x-axis and emits [x, y] point data", () => {
    const option = buildEChartsOption(scatterSpec, scatterData);
    const xAxis = option.xAxis as { type: string };
    expect(xAxis.type).toBe("value");
    const series = option.series as Array<{ type: string; data: number[][] }>;
    expect(series[0].type).toBe("scatter");
    expect(series[0].data).toEqual([
      [10, 4.2],
      [25, 3.8],
    ]);
  });
});

// ---------------------------------------------------------------------------
// Number (KPI) tiles — rendered without ECharts
// ---------------------------------------------------------------------------

describe("buildEChartsOption — number", () => {
  it("throws (number tiles are rendered by NumberRenderer, not ECharts)", () => {
    const numberSpec: ChartSpec = {
      type: "number",
      query: countQuery,
      encoding: { series: [{ field: "count", name: "Count" }] },
    };
    expect(() => buildEChartsOption(numberSpec, sampleQueryResponse)).toThrow(/number/);
  });
});

// ---------------------------------------------------------------------------
// Multiple series
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// v2 chart types + formatting (#8)
// ---------------------------------------------------------------------------

describe("buildEChartsOption — v2 types", () => {
  it("hbar uses a value xAxis and a category yAxis", () => {
    const option = buildEChartsOption({ ...barSpec, type: "hbar" }, sampleQueryResponse);
    expect((option.xAxis as { type: string }).type).toBe("value");
    const yAxis = option.yAxis as { type: string; data: string[] };
    expect(yAxis.type).toBe("category");
    expect(yAxis.data).toEqual(["alpha", "beta", "gamma"]);
  });

  it("gauge sums the series into one dial and omits the axes", () => {
    const gaugeSpec: ChartSpec = {
      type: "gauge",
      query: countQuery,
      encoding: { series: [{ field: "count" }] },
    };
    const option = buildEChartsOption(gaugeSpec, sampleQueryResponse);
    const series = option.series as Array<{ type: string; data: Array<{ value: number }> }>;
    expect(series[0].type).toBe("gauge");
    expect(series[0].data[0].value).toBe(42); // 10 + 25 + 7
    expect(option.xAxis).toBeUndefined();
  });

  it("combo renders the first series as bar and the rest as line", () => {
    const multiData: QueryResponse = {
      columns: ["month", "sales", "returns"],
      rows: [
        ["Jan", 100, 5],
        ["Feb", 120, 8],
      ],
      row_count: 2,
    };
    const comboSpec: ChartSpec = {
      type: "combo",
      query: countQuery,
      encoding: { x: "month", series: [{ field: "sales" }, { field: "returns" }] },
    };
    const series = buildEChartsOption(comboSpec, multiData).series as Array<{ type: string }>;
    expect(series[0].type).toBe("bar");
    expect(series[1].type).toBe("line");
  });

  it("donut renders a pie series with a ring radius", () => {
    const series = buildEChartsOption({ ...pieSpec, type: "donut" }, sampleQueryResponse)
      .series as Array<{ type: string; radius: string[] }>;
    expect(series[0].type).toBe("pie");
    expect(series[0].radius[0]).toBe("50%");
  });

  it("sorts categories by value descending", () => {
    const option = buildEChartsOption(
      { ...barSpec, options: { sort: "value_desc" } },
      sampleQueryResponse
    );
    // 25 (beta) > 10 (alpha) > 7 (gamma)
    expect((option.xAxis as { data: string[] }).data).toEqual(["beta", "alpha", "gamma"]);
  });
});

describe("buildEChartsOption — multiple series", () => {
  it("maps each series spec to an ECharts series entry", () => {
    const multiData: QueryResponse = {
      columns: ["month", "sales", "returns"],
      rows: [
        ["Jan", 100, 5],
        ["Feb", 120, 8],
      ],
      row_count: 2,
    };
    const multiSpec: ChartSpec = {
      type: "bar",
      query: countQuery,
      encoding: {
        x: "month",
        series: [
          { field: "sales", name: "Sales" },
          { field: "returns", name: "Returns" },
        ],
      },
    };
    const option = buildEChartsOption(multiSpec, multiData);
    const series = option.series as Array<{ name: string; data: number[] }>;
    expect(series).toHaveLength(2);
    expect(series[0]).toMatchObject({ name: "Sales", data: [100, 120] });
    expect(series[1]).toMatchObject({ name: "Returns", data: [5, 8] });
  });
});

// ---------------------------------------------------------------------------
// v2 shared chrome: legend.type and labels.show
// ---------------------------------------------------------------------------

describe("buildEChartsOption — v2 shared chrome", () => {
  it("maps legend.type plain and labels.show", () => {
    const opt = buildEChartsOption(
      {
        version: "2",
        type: "bar",
        query: { metric_refs: ["m"] },
        encoding: { x: "c", series: [{ field: "m" }] },
        options: { legend: { show: true, type: "plain" }, labels: { show: true } },
      },
      { columns: ["c", "m"], rows: [["a", 1]], row_count: 1 }
    ) as any;
    expect(opt.legend.type).toBe("plain");
    expect(opt.series[0].label.show).toBe(true);
  });

  it("itemTooltip always uses trigger 'item' for pie (no mode set)", () => {
    const opt = buildEChartsOption(
      {
        type: "pie",
        query: { metric_refs: ["m"] },
        encoding: { x: "c", series: [{ field: "m" }] },
        // no options.tooltip set — default must still be item
      },
      { columns: ["c", "m"], rows: [["a", 1]], row_count: 1 }
    ) as any;
    expect(opt.tooltip.trigger).toBe("item");
  });

  it("axisTooltip formatter includes a total line when show_total is true", () => {
    const opt = buildEChartsOption(
      {
        type: "bar",
        query: { metric_refs: ["m"] },
        encoding: { x: "c", series: [{ field: "m", name: "M" }] },
        options: { tooltip: { show_total: true } },
      },
      { columns: ["c", "m"], rows: [["a", 10], ["b", 20]], row_count: 2 }
    ) as any;
    // formatter must be a function (not valueFormatter)
    expect(typeof opt.tooltip.formatter).toBe("function");
    // call it with a mock params array
    const result = opt.tooltip.formatter([
      { seriesName: "M", value: 10, marker: "", axisValue: "a" },
    ]);
    expect(result).toContain("Total:");
  });

  it("date_format formats ISO date categories with token replacement", () => {
    const opt = buildEChartsOption(
      {
        type: "bar",
        query: { metric_refs: ["m"] },
        encoding: { x: "c", series: [{ field: "m" }] },
        options: { date_format: "%Y-%m" },
      },
      { columns: ["c", "m"], rows: [["2024-03-15", 5]], row_count: 1 }
    ) as any;
    // The formatted category should use the date_format pattern
    expect((opt.xAxis as { data: string[] }).data[0]).toBe("2024-03");
  });
});

// ---------------------------------------------------------------------------
// Cartesian family options (Task 5 — Slice A2)
// ---------------------------------------------------------------------------

const cartSpec = (cartesian: any, type: ChartSpec["type"] = "bar"): ChartSpec => ({
  version: "2", type, query: { metric_refs: ["m"] },
  encoding: { x: "c", series: [{ field: "m" }] },
  options: { type_options: { cartesian } },
});
const cartData = { columns: ["c", "m"], rows: [["a", 1], ["b", 3]], row_count: 2 };

it("cartesian stacked + percent normalises series to 100", () => {
  const opt = buildEChartsOption(cartSpec({ stacked: true, percent: true }), cartData) as any;
  expect(opt.series[0].stack).toBe("total");
  // With a single series each category total equals the series value,
  // so every normalised value is 100.
  expect(opt.series[0].data[0]).toBeCloseTo(100);
  expect(opt.series[0].data[1]).toBeCloseTo(100);
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

// ---------------------------------------------------------------------------
// Pie/donut family options (Task 6 — Slice A2)
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Gauge family options (Task 7 — Slice A2)
// ---------------------------------------------------------------------------

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

it("gauge clamps interval stops exceeding max to 1.0", () => {
  const opt = buildEChartsOption(
    { version: "2", type: "gauge", query: { metric_refs: ["m"] },
      encoding: { series: [{ field: "m" }] },
      options: { type_options: { gauge: { max: 100, intervals: [50, 9999], interval_colors: ["#0f0", "#f00"] } } } },
    { columns: ["m"], rows: [[42]], row_count: 1 }) as any;
  expect(opt.series[0].axisLine.lineStyle.color[1][0]).toBe(1);
});

// ---------------------------------------------------------------------------
// Funnel / Radar / Treemap family options (Task 8 — Slice A2)
// ---------------------------------------------------------------------------

it("radar shape circle + per-metric bounds", () => {
  const opt = buildEChartsOption(
    { version: "2", type: "radar", query: { metric_refs: ["a","b"] },
      encoding: { x: "c", series: [{ field: "a" }, { field: "b" }] },
      options: { type_options: { radar: { shape: "circle", metric_bounds: {} } } } },
    { columns: ["c","a","b"], rows: [["x",1,2],["y",3,4]], row_count: 2 }) as any;
  expect(opt.radar.shape).toBe("circle");
});
it("treemap show_upper_labels sets upperLabel.show", () => {
  const t = buildEChartsOption(
    { version: "2", type: "treemap", query: { metric_refs: ["m"] },
      encoding: { x: "c", series: [{ field: "m" }] },
      options: { type_options: { treemap: { show_upper_labels: true } } } },
    { columns: ["c","m"], rows: [["a",1]], row_count: 1 }) as any;
  expect(t.series[0].upperLabel.show).toBe(true);
});
it("funnel show_labels false hides series label", () => {
  const f = buildEChartsOption(
    { version: "2", type: "funnel", query: { metric_refs: ["m"] },
      encoding: { x: "c", series: [{ field: "m" }] },
      options: { type_options: { funnel: { show_labels: false } } } },
    { columns: ["c","m"], rows: [["a",10],["b",5]], row_count: 2 }) as any;
  expect(f.series[0].label.show).toBe(false);
});
it("funnel tooltip_label_type drives tooltip formatter", () => {
  const f = buildEChartsOption(
    { version: "2", type: "funnel", query: { metric_refs: ["m"] },
      encoding: { x: "c", series: [{ field: "m" }] },
      options: { type_options: { funnel: { tooltip_label_type: "value_percent", show_tooltip_labels: true } } } },
    { columns: ["c","m"], rows: [["a",10],["b",5]], row_count: 2 }) as any;
  expect(f.tooltip.formatter).toBe("{c} ({d}%)");
});

// ---------------------------------------------------------------------------
// Heatmap (Slice D)
// ---------------------------------------------------------------------------

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
    // Each datum is { value: [xIndex, yIndex, measure], $xCat, $yCat }.
    expect(option.series[0].data).toContainEqual({ value: [0, 0, 10], $xCat: "West", $yCat: "Jan" });
    expect(option.series[0].data).toContainEqual({ value: [1, 0, 5], $xCat: "East", $yCat: "Jan" });
    expect(option.visualMap.max).toBe(20);
    expect(option.series[0].label.show).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// ChartRendererHandle type guard
// ---------------------------------------------------------------------------

test("ChartRendererHandle exposes toPng", () => {
  const handle: ChartRendererHandle = { toPng: () => null };
  expect(handle.toPng()).toBeNull();
});

// ---------------------------------------------------------------------------
// Slice A2 final-review: legend.sort / tooltip.sort_by_metric /
//   labels.template+threshold / color_scheme / tooltip.time_format
// ---------------------------------------------------------------------------

const a2Data = { columns: ["c", "m1", "m2"], rows: [["a", 5, 30], ["b", 20, 10]], row_count: 2 };
const a2Spec = (opts: any): ChartSpec => ({
  version: "2", type: "bar", query: { metric_refs: ["m1", "m2"] },
  encoding: { x: "c", series: [{ field: "m1", name: "Zebra" }, { field: "m2", name: "Apple" }] },
  options: opts,
});

describe("legend.sort", () => {
  it("sort=asc orders legend data alphabetically ascending", () => {
    const opt = buildEChartsOption(a2Spec({ legend: { show: true, sort: "asc" } }), a2Data) as any;
    expect(opt.legend.data).toEqual(["Apple", "Zebra"]);
  });

  it("sort=desc orders legend data alphabetically descending", () => {
    const opt = buildEChartsOption(a2Spec({ legend: { show: true, sort: "desc" } }), a2Data) as any;
    expect(opt.legend.data).toEqual(["Zebra", "Apple"]);
  });

  it("sort=none (default) preserves original series order", () => {
    const opt = buildEChartsOption(a2Spec({ legend: { show: true, sort: "none" } }), a2Data) as any;
    expect(opt.legend.data).toEqual(["Zebra", "Apple"]);
  });
});

describe("tooltip.sort_by_metric", () => {
  it("sort_by_metric=true returns tooltip items sorted by value desc", () => {
    const opt = buildEChartsOption(
      a2Spec({ tooltip: { sort_by_metric: true, show_total: true } }),
      a2Data
    ) as any;
    expect(typeof opt.tooltip.formatter).toBe("function");
    const result: string = opt.tooltip.formatter([
      { seriesName: "Zebra", value: 5, marker: "", axisValue: "a" },
      { seriesName: "Apple", value: 30, marker: "", axisValue: "a" },
    ]);
    // Apple (30) should appear before Zebra (5) in the output
    expect(result.indexOf("Apple")).toBeLessThan(result.indexOf("Zebra"));
  });

  it("sort_by_metric=false preserves original tooltip order", () => {
    const opt = buildEChartsOption(
      a2Spec({ tooltip: { sort_by_metric: false, show_total: true } }),
      a2Data
    ) as any;
    const result: string = opt.tooltip.formatter([
      { seriesName: "Zebra", value: 5, marker: "", axisValue: "a" },
      { seriesName: "Apple", value: 30, marker: "", axisValue: "a" },
    ]);
    expect(result.indexOf("Zebra")).toBeLessThan(result.indexOf("Apple"));
  });
});

describe("labels.template and labels.threshold (non-pie)", () => {
  it("labels.template sets formatter on the data label", () => {
    const opt = buildEChartsOption(
      { version: "2", type: "bar", query: { metric_refs: ["m"] },
        encoding: { x: "c", series: [{ field: "m" }] },
        options: { labels: { show: true, template: "{c} units" } } },
      { columns: ["c", "m"], rows: [["a", 10]], row_count: 1 }
    ) as any;
    expect(opt.series[0].label.formatter).toBe("{c} units");
  });

  it("labels.threshold hides the label for values below the threshold", () => {
    const opt = buildEChartsOption(
      { version: "2", type: "bar", query: { metric_refs: ["m"] },
        encoding: { x: "c", series: [{ field: "m" }] },
        options: { labels: { show: true, threshold: 15 } } },
      { columns: ["c", "m"], rows: [["a", 5], ["b", 20]], row_count: 2 }
    ) as any;
    const formatter = opt.series[0].label.formatter as (p: { value: number }) => string;
    expect(typeof formatter).toBe("function");
    expect(formatter({ value: 5 })).toBe("");   // below threshold
    expect(formatter({ value: 20 })).not.toBe(""); // above threshold
  });

  it("labels.threshold + template: below threshold returns empty, above returns template", () => {
    const opt = buildEChartsOption(
      { version: "2", type: "bar", query: { metric_refs: ["m"] },
        encoding: { x: "c", series: [{ field: "m" }] },
        options: { labels: { show: true, threshold: 10, template: "{c}%" } } },
      { columns: ["c", "m"], rows: [["a", 3], ["b", 50]], row_count: 2 }
    ) as any;
    const formatter = opt.series[0].label.formatter as (p: { value: number }) => string;
    expect(formatter({ value: 3 })).toBe("");
    expect(formatter({ value: 50 })).toBe("{c}%");
  });
});

describe("color_scheme palette resolution", () => {
  it("color_scheme sets option.color when palette is empty", () => {
    const opt = buildEChartsOption(
      { version: "2", type: "bar", query: { metric_refs: ["m"] },
        encoding: { x: "c", series: [{ field: "m" }] },
        options: { color_scheme: "vibrant", palette: [] } },
      { columns: ["c", "m"], rows: [["a", 1]], row_count: 1 }
    ) as any;
    // The vibrant scheme starts with "#e6194b"
    expect(opt.color[0]).toBe("#e6194b");
  });

  it("explicit palette overrides color_scheme", () => {
    const opt = buildEChartsOption(
      { version: "2", type: "bar", query: { metric_refs: ["m"] },
        encoding: { x: "c", series: [{ field: "m" }] },
        options: { color_scheme: "vibrant", palette: ["#aabbcc"] } },
      { columns: ["c", "m"], rows: [["a", 1]], row_count: 1 }
    ) as any;
    expect(opt.color[0]).toBe("#aabbcc");
  });

  it("unknown color_scheme falls back to theme palette (array)", () => {
    const opt = buildEChartsOption(
      { version: "2", type: "bar", query: { metric_refs: ["m"] },
        encoding: { x: "c", series: [{ field: "m" }] },
        options: { color_scheme: "nonexistent_scheme_xyz" } },
      { columns: ["c", "m"], rows: [["a", 1]], row_count: 1 }
    ) as any;
    expect(Array.isArray(opt.color)).toBe(true);
  });
});

describe("tooltip.time_format", () => {
  it("time_format is applied to the axis header in the tooltip formatter", () => {
    const opt = buildEChartsOption(
      { version: "2", type: "bar", query: { metric_refs: ["m"] },
        encoding: { x: "c", series: [{ field: "m", name: "M" }] },
        options: { tooltip: { time_format: "%Y-%m", show_total: true } } },
      { columns: ["c", "m"], rows: [["2024-06-15", 10]], row_count: 1 }
    ) as any;
    expect(typeof opt.tooltip.formatter).toBe("function");
    const result: string = opt.tooltip.formatter([
      { seriesName: "M", value: 10, marker: "", axisValue: "2024-06-15" },
    ]);
    expect(result).toContain("2024-06");
  });

  it("time_format takes priority over date_format for tooltip header", () => {
    const opt = buildEChartsOption(
      { version: "2", type: "bar", query: { metric_refs: ["m"] },
        encoding: { x: "c", series: [{ field: "m", name: "M" }] },
        options: { date_format: "%Y", tooltip: { time_format: "%Y-%m", show_total: true } } },
      { columns: ["c", "m"], rows: [["2024-06-15", 5]], row_count: 1 }
    ) as any;
    const result: string = opt.tooltip.formatter([
      { seriesName: "M", value: 5, marker: "", axisValue: "2024-06-15" },
    ]);
    // tooltip.time_format wins: should show "2024-06", not "2024"
    expect(result).toContain("2024-06");
    expect(result).not.toMatch(/^2024<br/);
  });
});

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

  it("self-cycle: appends zero-width-space to target and label formatter strips it", () => {
    const cyclicData: QueryResponse = {
      columns: ["sales.region", "sales.product", "sales.total"],
      rows: [["West", "West", 5]],
      row_count: 1,
    };
    const option = buildEChartsOption(sankeySpec, cyclicData) as Record<string, any>;
    // The link target must carry the U+200B suffix so ECharts doesn't see a duplicate node name.
    expect(option.series[0].links).toContainEqual({ source: "West", target: "West​", value: 5 });
    // The label formatter must strip the suffix for display.
    expect(option.series[0].label.formatter({ name: "West​" } as any)).toBe("West");
  });
});

// ---------------------------------------------------------------------------
// selectionPairsFromClick (Task 6 — Slice D)
// ---------------------------------------------------------------------------

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
