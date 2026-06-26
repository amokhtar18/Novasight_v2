// frontend/src/test/dashboardDetailFilters.test.tsx  (replace contents)
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { DashboardDetail } from "@/pages/DashboardDetail";

const board = {
  id: "d1", name: "Board", description: null, owner_id: null,
  created_at: "", updated_at: "",
  native_filters: [{ id: "f1", kind: "value", member: "regional_sales.region", operator: "equals", label: "Region" }],
  tiles: [{
    id: "t1", kind: "chart", chart_id: "c", content: null, title: "Sales", position: 0, x: 0, y: 0, w: 6, h: 4,
    chart: { id: "c", name: "Sales", source_kind: "semantic", source_ref: null, owner_id: null, created_at: "", updated_at: "",
      spec: { type: "bar", query: { metric_refs: ["regional_sales.total_amount"] }, encoding: { x: "regional_sales.region", series: [{ field: "regional_sales.total_amount" }] } } },
  }],
};

vi.mock("@/api/hooks", async () => {
  const actual = await vi.importActual<typeof import("@/api/hooks")>("@/api/hooks");
  return {
    ...actual,
    useDashboard: () => ({ data: board, isLoading: false, isError: false }),
    useUpdateDashboard: () => ({ mutate: vi.fn() }),
    useAddDashboardTile: () => ({ mutate: vi.fn() }),
    useSemanticValues: () => ({ data: { values: ["west", "east"] }, isLoading: false }),
    useDeleteDashboardTile: () => ({ mutate: vi.fn() }),
    useUpdateDashboardTile: () => ({ mutate: vi.fn() }),
  };
});
vi.mock("@/lib/identity", () => ({ useIdentity: () => ({ canEdit: true }) }));
vi.mock("@/lib/useChartData", () => ({ useChartData: () => ({ data: { columns: [], rows: [], row_count: 0 }, isLoading: false, isError: false }) }));

function wrap() {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/dashboards/d1"]}>
        <Routes><Route path="/dashboards/:dashboardId" element={<DashboardDetail />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("DashboardDetail native filters", () => {
  it("renders the native-filter drawer with the configured filter", () => {
    wrap();
    expect(screen.getByText("Region")).toBeInTheDocument();
  });
});
