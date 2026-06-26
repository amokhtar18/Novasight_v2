/**
 * Tests for the Builder semantic-model path (#9).
 *
 * All API hooks are mocked (no network); ChartRenderer, NLChartPanel, and
 * AddToDashboard are stubbed so the test focuses on the builder wiring:
 * the semantic path is the default, renders the model/dimension/measure controls,
 * previews a chart, exposes the server-side Save action, and the source toggle
 * switches to the dataset path.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import type { QueryResponse, SemanticModelRead } from "@/types/api";

const model: SemanticModelRead = {
  name: "regional_sales",
  title: "Regional Sales",
  measures: [{ name: "regional_sales.total_amount", title: "Total Amount", type: "number" }],
  dimensions: [{ name: "regional_sales.region", title: "Region", type: "string" }],
};

const queryData: QueryResponse = {
  columns: ["regional_sales.region", "regional_sales.total_amount"],
  rows: [
    ["west", 100.5],
    ["east", 200],
  ],
  row_count: 2,
};

function idleQuery<T>(data: T) {
  return { data, isLoading: false, isError: false, error: null };
}

function idleMutation() {
  return { mutate: vi.fn(), isPending: false };
}

vi.mock("@/api/hooks", () => ({
  useSemanticModels: vi.fn(),
  useSemanticQuery: vi.fn(),
  useCreateChart: vi.fn(),
  useCharts: vi.fn(),
  useDeleteChart: vi.fn(),
}));

vi.mock("@/components/chart/ChartRenderer", () => ({
  ChartRenderer: ({ title }: { title?: string }) => (
    <div role="img" aria-label={title ?? "chart"} data-testid="chart-renderer" />
  ),
}));
vi.mock("@/components/chart/NLChartPanel", () => ({
  NLChartPanel: () => <div data-testid="nl-chart-panel" />,
}));
vi.mock("@/components/dashboard/AddToDashboard", () => ({
  AddToDashboard: () => <button type="button">Add to dashboard</button>,
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { Builder } from "@/pages/Builder";
import {
  useCharts,
  useCreateChart,
  useDeleteChart,
  useSemanticModels,
  useSemanticQuery,
} from "@/api/hooks";

const mockSemanticModels = vi.mocked(useSemanticModels);
const mockSemanticQuery = vi.mocked(useSemanticQuery);
const mockCreateChart = vi.mocked(useCreateChart);
const mockCharts = vi.mocked(useCharts);
const mockDeleteChart = vi.mocked(useDeleteChart);

beforeEach(() => {
  // @ts-expect-error partial mock
  mockSemanticModels.mockReturnValue(idleQuery([model]));
  // @ts-expect-error partial mock
  mockSemanticQuery.mockReturnValue(idleQuery(queryData));
  // @ts-expect-error partial mock
  mockCreateChart.mockReturnValue(idleMutation());
  // @ts-expect-error partial mock
  mockCharts.mockReturnValue(idleQuery([]));
  // @ts-expect-error partial mock
  mockDeleteChart.mockReturnValue(idleMutation());
});

afterEach(() => vi.clearAllMocks());

function renderBuilder() {
  return render(
    <MemoryRouter>
      <Builder />
    </MemoryRouter>
  );
}

describe("Builder — semantic path (semantic-only, #8)", () => {
  it("lists governed model/dimension/measure members", () => {
    renderBuilder();

    // The model select renders with the governed title; dimensions and measures appear
    // as draggable fields placed on the shelves (seeded defaults).
    expect((screen.getByLabelText(/^model$/i) as HTMLSelectElement).value).toBe("regional_sales");
    expect(screen.getByText("Region")).toBeInTheDocument();
    expect(screen.getByText("Total Amount")).toBeInTheDocument();
    // The Superset-style shelves are present.
    expect(screen.getByText(/^x-axis$/i)).toBeInTheDocument();
    expect(screen.getByText(/^breakdown \(series\)$/i)).toBeInTheDocument();
    expect(screen.getByText(/^metrics$/i)).toBeInTheDocument();
  });

  it("previews the chart and exposes the server-side Save action", () => {
    renderBuilder();

    expect(screen.getByTestId("chart-renderer")).toBeInTheDocument();
    // The new server-side persistence action is present (from SaveChartButton).
    expect(screen.getByRole("button", { name: /save chart/i })).toBeInTheDocument();
  });

  it("runs the semantic query with the selected measure + dimension", () => {
    renderBuilder();
    expect(mockSemanticQuery).toHaveBeenCalledWith(
      expect.objectContaining({
        measures: ["regional_sales.total_amount"],
        dimensions: ["regional_sales.region"],
      })
    );
  });

  it("rolls a time dimension up by granularity via time_dimensions", () => {
    const timeModel: SemanticModelRead = {
      name: "sales",
      title: "Sales",
      measures: [{ name: "sales.total", title: "Total", type: "number" }],
      dimensions: [{ name: "sales.created_at", title: "Created At", type: "time" }],
    };
    // @ts-expect-error partial mock
    mockSemanticModels.mockReturnValue(idleQuery([timeModel]));
    renderBuilder();

    // A granularity control appears only for a time-typed dimension, defaulting to month.
    const gran = screen.getByLabelText(/granularity/i) as HTMLSelectElement;
    expect(gran.value).toBe("month");

    // The query groups via Cube timeDimensions (not a plain dimension), so the rolled-up
    // <dimension>.<granularity> column can be the chart's time axis.
    expect(mockSemanticQuery).toHaveBeenCalledWith(
      expect.objectContaining({
        measures: ["sales.total"],
        dimensions: [],
        time_dimensions: [{ dimension: "sales.created_at", granularity: "month" }],
      })
    );

    // Changing the granularity re-issues the query at the new bucket.
    fireEvent.change(gran, { target: { value: "quarter" } });
    expect(mockSemanticQuery).toHaveBeenCalledWith(
      expect.objectContaining({
        time_dimensions: [{ dimension: "sales.created_at", granularity: "quarter" }],
      })
    );
  });
});
