/**
 * Tests for the Charts library page (#9).
 *
 * API hooks, identity, the chart-data hook, and heavy child components are mocked
 * so the test focuses on the list wiring: it renders saved charts with their type +
 * source, exposes delete for editors, and shows the empty state.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import type { QueryResponse, SavedChartRead } from "@/types/api";

vi.mock("@/api/hooks", () => ({ useCharts: vi.fn(), useDeleteChart: vi.fn() }));
vi.mock("@/lib/identity", () => ({ useIdentity: vi.fn() }));
vi.mock("@/lib/useChartData", () => ({ useChartData: vi.fn() }));
vi.mock("@/components/chart/ChartRenderer", () => ({
  ChartRenderer: () => <div data-testid="chart-renderer" />,
}));
vi.mock("@/components/dashboard/AddToDashboard", () => ({
  AddToDashboard: () => <button type="button">Add to dashboard</button>,
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { Charts } from "@/pages/Charts";
import { useCharts, useDeleteChart } from "@/api/hooks";
import { useIdentity } from "@/lib/identity";
import { useChartData } from "@/lib/useChartData";

const chart: SavedChartRead = {
  id: "c1",
  name: "Sales by region",
  spec: {
    type: "bar",
    query: { metric_refs: ["regional_sales.total"] },
    encoding: { x: "regional_sales.region", series: [{ field: "regional_sales.total" }] },
    options: { title: "Sales by region" },
  },
  source_kind: "semantic",
  source_ref: "regional_sales",
  owner_id: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-06-01T00:00:00Z",
};

const queryData: QueryResponse = {
  columns: ["regional_sales.region", "regional_sales.total"],
  rows: [["west", 100]],
  row_count: 1,
};

function setup(charts: SavedChartRead[]) {
  // @ts-expect-error partial mock
  vi.mocked(useCharts).mockReturnValue({ data: charts, isLoading: false });
  // @ts-expect-error partial mock
  vi.mocked(useDeleteChart).mockReturnValue({ mutate: vi.fn() });
  // @ts-expect-error partial mock
  vi.mocked(useIdentity).mockReturnValue({ canEdit: true });
  // @ts-expect-error partial mock
  vi.mocked(useChartData).mockReturnValue({ data: queryData, isLoading: false, isError: false });
}

afterEach(() => vi.clearAllMocks());

beforeEach(() => setup([chart]));

function renderCharts() {
  return render(
    <MemoryRouter>
      <Charts />
    </MemoryRouter>
  );
}

describe("Charts page", () => {
  it("lists a saved chart with its type, source, and delete control", () => {
    renderCharts();
    expect(screen.getByText("Sales by region")).toBeInTheDocument();
    expect(screen.getByText("Bar")).toBeInTheDocument(); // humanized chart type
    expect(screen.getByText("regional_sales")).toBeInTheDocument(); // source ref
    expect(screen.getByRole("button", { name: /delete sales by region/i })).toBeInTheDocument();
    expect(screen.getByTestId("chart-renderer")).toBeInTheDocument();
  });

  it("shows the empty state when there are no charts", () => {
    setup([]);
    renderCharts();
    expect(screen.getByText(/no saved charts yet/i)).toBeInTheDocument();
  });
});
