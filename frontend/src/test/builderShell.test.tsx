/**
 * Tests for the Builder shell: drawer toggle, header wiring.
 *
 * Mocks are identical to builderSemantic.test.tsx so the same Builder
 * component renders cleanly in both suites.
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

describe("Builder — shell (drawer + header)", () => {
  it("opens the saved-charts drawer from the toolbar", () => {
    renderBuilder();
    expect(screen.queryByRole("heading", { name: /saved charts/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /saved charts/i }));
    expect(screen.getByRole("heading", { name: /saved charts/i })).toBeInTheDocument();
  });
});
