/**
 * Unit tests for ChartRenderer's buildEChartsOption mapping function.
 *
 * Tests run in Node (no DOM needed) since we test pure data transformation.
 */

import { describe, it, expect } from "vitest";
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
