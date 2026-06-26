import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";

import type { ChartSpec, QueryResponse, SemanticModelRead } from "@/types/api";

// Ground the modal: governed models come from useSemanticModels, the re-pivot runs
// through useChartData (a structured /semantic/query — never raw SQL), and the chart
// itself is the shared ChartRenderer (stubbed here to expose the derived spec it gets).
vi.mock("@/api/hooks", () => ({ useSemanticModels: vi.fn() }));
vi.mock("@/lib/useChartData", () => ({ useChartData: vi.fn() }));
vi.mock("@/components/chart/ChartRenderer", () => ({
  ChartRenderer: ({ spec }: { spec: ChartSpec }) => (
    <div
      data-testid="chart"
      data-x={spec.encoding.x}
      data-dims={(spec.query.dimensions ?? []).join(",")}
      data-metrics={(spec.query.metric_refs ?? []).join(",")}
    />
  ),
}));

import { buildDrillBySpec, DrillByModal } from "@/components/chart/DrillByModal";
import { useSemanticModels } from "@/api/hooks";
import { useChartData } from "@/lib/useChartData";

const mockModels = vi.mocked(useSemanticModels);
const mockChartData = vi.mocked(useChartData);

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

// --- Component-level coverage (the modal wiring, not just the builder) ---

const models: SemanticModelRead[] = [
  {
    name: "regional_sales",
    title: "Regional Sales",
    measures: [{ name: "regional_sales.total_amount", title: "Total", type: "number" }],
    dimensions: [
      { name: "regional_sales.region", title: "Region", type: "string" },
      { name: "regional_sales.product", title: "Product", type: "string" },
    ],
  },
];

const tileData: QueryResponse = {
  columns: ["regional_sales.region", "regional_sales.total_amount"],
  rows: [["west", 100], ["east", 50]],
  row_count: 2,
};

const result: QueryResponse = {
  columns: ["regional_sales.product", "regional_sales.total_amount"],
  rows: [["Widget", 10]],
  row_count: 1,
};

beforeEach(() => {
  // @ts-expect-error partial mock
  mockModels.mockReturnValue({ data: models });
  // @ts-expect-error partial mock
  mockChartData.mockReturnValue({ data: result, isLoading: false });
});

afterEach(() => vi.clearAllMocks());

function renderModal() {
  return render(
    <DrillByModal open onOpenChange={vi.fn()} spec={base} tileFilters={[]} data={tileData} />
  );
}

describe("DrillByModal", () => {
  it("offers only same-cube governed dimensions, excluding the current x-axis", () => {
    renderModal();
    const dim = screen.getByLabelText("Dimension");
    expect(within(dim).getByRole("option", { name: "Product" })).toBeInTheDocument();
    // The base x-axis dimension is not offered as a re-pivot target.
    expect(within(dim).queryByRole("option", { name: "Region" })).not.toBeInTheDocument();
    // Nothing is queried or charted until a dimension is chosen.
    expect(screen.getByText(/pick a dimension/i)).toBeInTheDocument();
    expect(mockChartData).toHaveBeenLastCalledWith(null);
  });

  it("re-pivots through a grounded query and renders the derived chart", () => {
    renderModal();
    fireEvent.change(screen.getByLabelText("Dimension"), {
      target: { value: "regional_sales.product" },
    });

    // useChartData ran on a structured spec (no SQL); metric is unchanged, dimension swapped.
    const calls = mockChartData.mock.calls;
    const derived = calls[calls.length - 1][0] as ChartSpec;
    expect(derived.query.metric_refs).toEqual(["regional_sales.total_amount"]);
    expect(derived.query.dimensions).toEqual(["regional_sales.product"]);

    const chart = screen.getByTestId("chart");
    expect(chart).toHaveAttribute("data-dims", "regional_sales.product");
    expect(chart).toHaveAttribute("data-metrics", "regional_sales.total_amount");
  });

  it("focusing a point adds an equals filter to the grounded query", () => {
    renderModal();
    fireEvent.change(screen.getByLabelText("Dimension"), {
      target: { value: "regional_sales.product" },
    });
    fireEvent.change(screen.getByLabelText(/Focus/), { target: { value: "west" } });

    const calls = mockChartData.mock.calls;
    const derived = calls[calls.length - 1][0] as ChartSpec;
    expect(derived.query.filters).toContainEqual({
      member: "regional_sales.region",
      operator: "equals",
      values: ["west"],
    });
  });
});
