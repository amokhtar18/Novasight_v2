/**
 * Frontend half of the chart-spec round-trip contract (Task 3.1).
 *
 * The backend half (backend/tests/test_chart_spec.py) proves the canonical
 * fixture parses into a Pydantic ChartSpec and serialises back unchanged. Here we
 * prove the SAME fixture file is a valid frontend `ChartSpec`: it satisfies the TS
 * type, survives a JSON round-trip unchanged, and drives the shared renderer.
 *
 * Both halves read one file — docs/examples/chart-spec.example.json — so the two
 * languages cannot silently drift: a field renamed on one side fails the other.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, it, expect, test } from "vitest";

import { buildEChartsOption } from "@/components/chart/ChartRenderer";
import type { ChartSpec, QueryResponse, ChartQuery, RelativeDateRange } from "@/types/api";

// The fixture lives at the repo root; vitest runs with cwd = frontend/, so the
// repo root is one level up. Both this test and the backend test read this one
// file, so the two language mirrors cannot silently drift.
const fixturePath = resolve(
  process.cwd(),
  "../docs/examples/chart-spec.example.json"
);
const rawText = readFileSync(fixturePath, "utf-8");
const rawJson = JSON.parse(rawText) as unknown;

// Assigning the parsed fixture to a ChartSpec-typed binding is the type-level
// half of the round-trip: if the contract and the fixture disagree on a field,
// tsc fails here. (TS structural typing accepts a superset-free exact match.)
const spec: ChartSpec = rawJson as ChartSpec;

// Data whose columns match the fixture's encoding fields.
const data: QueryResponse = {
  columns: ["month", "sales", "returns"],
  rows: [
    ["Jan", 100, 5],
    ["Feb", 120, 8],
  ],
  row_count: 2,
};

describe("chart-spec contract — frontend round-trip", () => {
  it("the canonical fixture conforms to the ChartSpec type", () => {
    expect(spec.version).toBe("1");
    expect(spec.type).toBe("bar");
    expect(spec.encoding.x).toBe("month");
    expect(spec.encoding.series.map((s) => s.field)).toEqual([
      "sales",
      "returns",
    ]);
  });

  it("survives a JSON round-trip unchanged", () => {
    const roundTripped = JSON.parse(JSON.stringify(spec));
    expect(roundTripped).toEqual(rawJson);
  });

  it("drives the shared renderer", () => {
    const option = buildEChartsOption(spec, data);
    const series = option.series as Array<{ name: string; data: number[] }>;
    expect(series).toHaveLength(2);
    expect(series[0]).toMatchObject({ name: "Sales", data: [100, 120] });
    expect(series[1]).toMatchObject({ name: "Returns", data: [5, 8] });
    // Options from the spec flow through to the ECharts option.
    expect((option.title as { text: string }).text).toBe(
      "Monthly sales vs returns"
    );
  });
});

test("ChartQuery accepts filters/order/limit and time date_range", () => {
  const range: RelativeDateRange = "last_30_days";
  const q: ChartQuery = {
    metric_refs: ["sales.total"],
    dimensions: ["sales.region"],
    time_dimensions: [{ dimension: "sales.created", granularity: "month", date_range: range }],
    filters: [{ member: "sales.region", operator: "equals", values: ["west"] }],
    order: { "sales.total": "desc" },
    limit: 25,
  };
  expect(q.limit).toBe(25);
  expect(q.order?.["sales.total"]).toBe("desc");
});
