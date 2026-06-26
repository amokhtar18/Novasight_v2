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
