/**
 * Unit tests for ChartRenderer's buildEChartsOption mapping function.
 *
 * Tests run in Node (no DOM needed) since we test pure data transformation.
 */

import { describe, it, expect, test } from "vitest";
import type { ChartRendererHandle } from "@/components/chart/ChartRenderer";
import { buildEChartsOption } from "@/components/chart/ChartRenderer";
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
// ChartRendererHandle type guard
// ---------------------------------------------------------------------------

test("ChartRendererHandle exposes toPng", () => {
  const handle: ChartRendererHandle = { toPng: () => null };
  expect(handle.toPng()).toBeNull();
});
