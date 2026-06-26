import { describe, expect, it } from "vitest";

import { buildDrillBySpec } from "@/components/chart/DrillByModal";
import type { ChartSpec } from "@/types/api";

const base: ChartSpec = {
  type: "bar", query: { metric_refs: ["regional_sales.total_amount"] },
  encoding: { x: "regional_sales.region", series: [{ field: "regional_sales.total_amount" }] },
};

describe("buildDrillBySpec", () => {
  it("re-groups by the chosen dimension and filters to the focus point", () => {
    const out = buildDrillBySpec(base, "regional_sales.product", { member: "regional_sales.region", value: "west" }, []);
    expect(out.query.metric_refs).toEqual(["regional_sales.total_amount"]);
    expect(out.query.dimensions).toEqual(["regional_sales.product"]);
    expect(out.encoding.x).toBe("regional_sales.product");
    expect(out.query.filters).toContainEqual({ member: "regional_sales.region", operator: "equals", values: ["west"] });
  });

  it("merges active tile filters and omits the point filter when no point is focused", () => {
    const out = buildDrillBySpec(base, "regional_sales.product", null, [{ member: "regional_sales.region", operator: "equals", values: ["east"] }]);
    expect(out.query.filters).toEqual([{ member: "regional_sales.region", operator: "equals", values: ["east"] }]);
  });
});
