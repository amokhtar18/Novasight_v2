import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import type {
  ChartSpec,
  QueryResponse,
  SemanticModelRead,
  SemanticQueryRequest,
} from "@/types/api";

// Ground the modal: governed models from useSemanticModels, and the breakdown runs as
// a structured /semantic/query via useSemanticQuery — NOT raw rows. TableRenderer is the
// real component (a plain HTML table) so the rendered result is asserted end-to-end.
vi.mock("@/api/hooks", () => ({
  useSemanticModels: vi.fn(),
  useSemanticQuery: vi.fn(),
}));

import { buildDetailRequest, DrillToDetailModal } from "@/components/chart/DrillToDetailModal";
import { useSemanticModels, useSemanticQuery } from "@/api/hooks";

const mockModels = vi.mocked(useSemanticModels);
const mockQuery = vi.mocked(useSemanticQuery);

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

// --- Component-level coverage (the modal wiring, not just the builder) ---

const tileData: QueryResponse = {
  columns: ["regional_sales.region", "regional_sales.total_amount"],
  rows: [["west", 100], ["east", 50]],
  row_count: 2,
};

const detailResult: QueryResponse = {
  columns: ["regional_sales.product", "regional_sales.total_amount"],
  rows: [["Widget", 42]],
  row_count: 1,
};

beforeEach(() => {
  // @ts-expect-error partial mock
  mockModels.mockReturnValue({ data: models });
  // @ts-expect-error partial mock
  mockQuery.mockReturnValue({ data: detailResult, isLoading: false });
});

afterEach(() => vi.clearAllMocks());

describe("DrillToDetailModal", () => {
  it("runs a grounded breakdown by the remaining governed dimensions and renders the table", () => {
    render(<DrillToDetailModal open onOpenChange={vi.fn()} spec={spec} tileFilters={[]} data={tileData} />);

    const calls = mockQuery.mock.calls;
    const req = calls[calls.length - 1][0] as SemanticQueryRequest;
    expect(req.measures).toEqual(["regional_sales.total_amount"]);
    expect(req.dimensions).toEqual(["regional_sales.product"]); // encoded x (region) excluded
    // The grounded result renders as a table, not raw SQL output.
    expect(screen.getByText("Widget")).toBeInTheDocument();
  });

  it("does not query while closed", () => {
    render(<DrillToDetailModal open={false} onOpenChange={vi.fn()} spec={spec} tileFilters={[]} data={tileData} />);
    expect(mockQuery).toHaveBeenLastCalledWith(null);
  });

  it("focusing a point filters the grounded breakdown to that point", () => {
    render(<DrillToDetailModal open onOpenChange={vi.fn()} spec={spec} tileFilters={[]} data={tileData} />);
    fireEvent.change(screen.getByLabelText(/Focus/), { target: { value: "east" } });

    const calls = mockQuery.mock.calls;
    const req = calls[calls.length - 1][0] as SemanticQueryRequest;
    expect(req.filters).toContainEqual({
      member: "regional_sales.region",
      operator: "equals",
      values: ["east"],
    });
  });

  it("excludes the breakdown dimension from the detail breakdown", () => {
    const heatmapSpec: ChartSpec = {
      type: "heatmap",
      query: { metric_refs: ["regional_sales.total_amount"], dimensions: ["regional_sales.region"] },
      encoding: { x: "regional_sales.region", series: [{ field: "regional_sales.total_amount" }], breakdown: ["regional_sales.product"] },
    };
    const req = buildDetailRequest(heatmapSpec, models, null, []);
    expect(req?.dimensions).not.toContain("regional_sales.region");
    expect(req?.dimensions).not.toContain("regional_sales.product");
  });
});
