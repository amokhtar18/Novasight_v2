// frontend/src/test/dashboardFilters.test.ts
import { describe, expect, it } from "vitest";

import {
  cubeOf, defaultSelection, filterAppliesToTile, resolveTileFilters,
} from "@/lib/dashboardFilters";
import type { DashboardTileRead, NativeFilter } from "@/types/api";

function tile(metric: string, id = "t1"): DashboardTileRead {
  return {
    id, kind: "chart", chart_id: "c", content: null, title: null,
    position: 0, x: 0, y: 0, w: 6, h: 4,
    chart: {
      id: "c", name: "C", source_kind: "semantic", source_ref: null, owner_id: null,
      created_at: "", updated_at: "",
      spec: { type: "bar", query: { metric_refs: [metric] }, encoding: { x: "regional_sales.region", series: [{ field: metric }] } },
    },
  } as DashboardTileRead;
}

const valueF: NativeFilter = { id: "f1", kind: "value", member: "regional_sales.region", operator: "equals" };
const numericF: NativeFilter = { id: "f2", kind: "numeric", member: "regional_sales.sales_rank" };
const timeF: NativeFilter = { id: "f3", kind: "time", member: "regional_sales.region" };

describe("cubeOf", () => {
  it("returns the prefix before the first dot", () => {
    expect(cubeOf("regional_sales.region")).toBe("regional_sales");
    expect(cubeOf("nodot")).toBeUndefined();
  });
});

describe("filterAppliesToTile", () => {
  it("auto scope applies to a cube-compatible tile", () => {
    expect(filterAppliesToTile(valueF, tile("regional_sales.total_amount"))).toBe(true);
  });
  it("never applies to an incompatible cube even in tile scope", () => {
    const scoped: NativeFilter = { ...valueF, scope: { mode: "tiles", tile_ids: ["t1"] } };
    expect(filterAppliesToTile(scoped, tile("other_cube.x"))).toBe(false);
  });
  it("tile scope excludes tiles not in tile_ids", () => {
    const scoped: NativeFilter = { ...valueF, scope: { mode: "tiles", tile_ids: ["other"] } };
    expect(filterAppliesToTile(scoped, tile("regional_sales.total_amount"))).toBe(false);
  });
});

describe("resolveTileFilters", () => {
  const t = tile("regional_sales.total_amount");
  it("value selection → a SemanticFilter", () => {
    const out = resolveTileFilters([valueF], { f1: { kind: "value", values: ["west", "east"] } }, t);
    expect(out.filters).toEqual([{ member: "regional_sales.region", operator: "equals", values: ["west", "east"] }]);
  });
  it("empty value selection contributes nothing", () => {
    const out = resolveTileFilters([valueF], { f1: { kind: "value", values: [] } }, t);
    expect(out.filters).toEqual([]);
  });
  it("numeric selection → gte/lte filters", () => {
    const out = resolveTileFilters([numericF], { f2: { kind: "numeric", min: 1, max: 5 } }, t);
    expect(out.filters).toEqual([
      { member: "regional_sales.sales_rank", operator: "gte", values: ["1"] },
      { member: "regional_sales.sales_rank", operator: "lte", values: ["5"] },
    ]);
  });
  it("time selection → a dateRange keyed by member", () => {
    const out = resolveTileFilters([timeF], { f3: { kind: "time", date_range: "last_30_days" } }, t);
    expect(out.dateRanges).toEqual({ "regional_sales.region": "last_30_days" });
  });
});

describe("defaultSelection", () => {
  it("seeds a value selection from default_values", () => {
    expect(defaultSelection({ ...valueF, default_values: ["west"] })).toEqual({ kind: "value", values: ["west"] });
  });
});
