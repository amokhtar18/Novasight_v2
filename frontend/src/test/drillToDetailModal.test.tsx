import { describe, expect, it } from "vitest";

import { buildDetailRequest } from "@/components/chart/DrillToDetailModal";
import type { ChartSpec, SemanticModelRead } from "@/types/api";

const spec: ChartSpec = {
  type: "bar", query: { metric_refs: ["regional_sales.total_amount"], dimensions: ["regional_sales.region"] },
  encoding: { x: "regional_sales.region", series: [{ field: "regional_sales.total_amount" }] },
};
const models: SemanticModelRead[] = [{
  name: "regional_sales", title: "Regional Sales",
  measures: [{ name: "regional_sales.total_amount", title: "Total", type: "number" }],
  dimensions: [
    { name: "regional_sales.region", title: "Region", type: "string" },
    { name: "regional_sales.product", title: "Product", type: "string" },
  ],
}];

describe("buildDetailRequest", () => {
  it("breaks the metric down by the remaining governed dimensions, filtered to the point", () => {
    const req = buildDetailRequest(spec, models, { member: "regional_sales.region", value: "west" }, []);
    expect(req?.measures).toEqual(["regional_sales.total_amount"]);
    expect(req?.dimensions).toEqual(["regional_sales.product"]); // region already encoded → excluded
    expect(req?.filters).toContainEqual({ member: "regional_sales.region", operator: "equals", values: ["west"] });
  });
});
