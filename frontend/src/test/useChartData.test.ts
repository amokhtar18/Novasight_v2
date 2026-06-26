import { describe, expect, it } from "vitest";
import { buildSemanticRequest } from "@/lib/useChartData";
import type { ChartSpec, SemanticFilter } from "@/types/api";

function specWith(query: Partial<ChartSpec["query"]>): ChartSpec {
  return {
    version: "1",
    type: "bar",
    query: { metric_refs: ["s.total"], dimensions: ["s.region"], ...query },
    encoding: { x: "s.region", series: [{ field: "s.total" }] },
  };
}

describe("buildSemanticRequest", () => {
  it("forwards order and limit from the spec", () => {
    const req = buildSemanticRequest(specWith({ order: { "s.total": "desc" }, limit: 25 }));
    expect(req?.order).toEqual({ "s.total": "desc" });
    expect(req?.limit).toBe(25);
  });

  it("defaults limit to 200 when the spec carries none", () => {
    expect(buildSemanticRequest(specWith({}))?.limit).toBe(200);
  });

  it("merges spec filters with view-time filters (spec first)", () => {
    const specFilter: SemanticFilter = { member: "s.region", operator: "equals", values: ["west"] };
    const viewFilter: SemanticFilter = { member: "s.tier", operator: "equals", values: ["gold"] };
    const req = buildSemanticRequest(specWith({ filters: [specFilter] }), [viewFilter]);
    expect(req?.filters).toEqual([specFilter, viewFilter]);
  });

  it("returns null for a non-semantic (dataset) spec", () => {
    const spec = specWith({});
    spec.query.metric_refs = [];
    expect(buildSemanticRequest(spec)).toBeNull();
  });
});

const spec: ChartSpec = {
  type: "line",
  query: {
    metric_refs: ["regional_sales.total_amount"],
    time_dimensions: [{ dimension: "regional_sales.order_date", granularity: "month" }],
  },
  encoding: { x: "regional_sales.order_date.month", series: [{ field: "regional_sales.total_amount" }] },
};

describe("buildSemanticRequest date_range override", () => {
  it("injects a view-time date_range onto the matching time dimension", () => {
    const req = buildSemanticRequest(spec, undefined, { "regional_sales.order_date": "last_30_days" });
    expect(req?.time_dimensions?.[0].date_range).toBe("last_30_days");
  });

  it("leaves time dimensions unchanged when no override matches", () => {
    const req = buildSemanticRequest(spec, undefined, { "other.dim": "last_7_days" });
    expect(req?.time_dimensions?.[0].date_range).toBeUndefined();
  });

  it("merges spec + view-time filters (spec first)", () => {
    const withFilter: ChartSpec = { ...spec, query: { ...spec.query, filters: [{ member: "regional_sales.region", operator: "equals", values: ["west"] }] } };
    const req = buildSemanticRequest(withFilter, [{ member: "regional_sales.region", operator: "equals", values: ["east"] }]);
    expect(req?.filters).toHaveLength(2);
    expect(req?.filters?.[0].values).toEqual(["west"]);
  });
});
