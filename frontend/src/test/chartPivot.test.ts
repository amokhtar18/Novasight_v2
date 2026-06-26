/**
 * Tests for applyBreakdown — the long→wide pivot that turns breakdown dimensions
 * into one series column each, so a multi-dimension chart needs no special renderer.
 */

import { describe, it, expect } from "vitest";

import { applyBreakdown } from "@/lib/chartPivot";
import type { ChartSpec, QueryResponse } from "@/types/api";

const data: QueryResponse = {
  columns: ["sales.region", "sales.channel", "sales.total"],
  rows: [
    ["west", "online", 10],
    ["west", "store", 5],
    ["east", "online", 7],
    ["east", "store", 3],
  ],
  row_count: 4,
};

function specWith(breakdown: string[], type: ChartSpec["type"] = "bar"): ChartSpec {
  return {
    version: "1",
    type,
    query: { metric_refs: ["sales.total"], dimensions: ["sales.region", "sales.channel"] },
    encoding: {
      x: "sales.region",
      series: [{ field: "sales.total", name: "Total" }],
      breakdown,
    },
  };
}

describe("applyBreakdown", () => {
  it("pivots a breakdown dimension into one series per distinct value", () => {
    const { spec, data: wide } = applyBreakdown(specWith(["sales.channel"]), data);

    // Columns become [x, ...distinct breakdown values]; one row per x category.
    expect(wide.columns).toEqual(["sales.region", "online", "store"]);
    expect(wide.rows).toEqual([
      ["west", 10, 5],
      ["east", 7, 3],
    ]);
    // The encoding now has one series per breakdown value and no leftover breakdown.
    expect(spec.encoding.series.map((s) => s.field)).toEqual(["online", "store"]);
    expect(spec.encoding.breakdown).toEqual([]);
  });

  it("sums duplicate (x, series) combinations", () => {
    const dup: QueryResponse = {
      columns: ["sales.region", "sales.channel", "sales.total"],
      rows: [
        ["west", "online", 10],
        ["west", "online", 4],
      ],
      row_count: 2,
    };
    const { data: wide } = applyBreakdown(specWith(["sales.channel"]), dup);
    expect(wide.rows).toEqual([["west", 14]]);
  });

  it("returns the inputs unchanged when there is no breakdown", () => {
    const spec = specWith([]);
    const out = applyBreakdown(spec, data);
    expect(out.spec).toBe(spec);
    expect(out.data).toBe(data);
  });

  it("does not pivot chart types without multiple series (e.g. pie)", () => {
    const spec = specWith(["sales.channel"], "pie");
    const out = applyBreakdown(spec, data);
    expect(out.spec).toBe(spec);
    expect(out.data).toBe(data);
  });
});
