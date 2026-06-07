/**
 * Tests for AddToDashboard — server-side pin flow (#10).
 *
 * Hooks + toast are mocked (no network). Covers the chained flow: when no
 * dashboard exists, Save creates the chart, creates a dashboard, and adds a tile
 * referencing the new chart; the saved chart's source is derived from the spec.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import type { ChartSpec } from "@/types/api";

vi.mock("@/api/hooks", () => ({
  useDashboards: vi.fn(),
  useCreateChart: vi.fn(),
  useCreateDashboard: vi.fn(),
  useAddDashboardTile: vi.fn(),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { AddToDashboard } from "@/components/dashboard/AddToDashboard";
import {
  useAddDashboardTile,
  useCreateChart,
  useCreateDashboard,
  useDashboards,
} from "@/api/hooks";
import { toast } from "sonner";

const mockDashboards = vi.mocked(useDashboards);
const mockCreateChart = vi.mocked(useCreateChart);
const mockCreateDashboard = vi.mocked(useCreateDashboard);
const mockAddTile = vi.mocked(useAddDashboardTile);

const spec: ChartSpec = {
  version: "1",
  type: "bar",
  query: { metric_refs: ["regional_sales.total_amount"] },
  encoding: {
    x: "regional_sales.region",
    series: [{ field: "regional_sales.total_amount", name: "Total" }],
  },
  options: { title: "Total by region" },
};

function mutation<T>(resolved: T) {
  return { mutate: vi.fn(), mutateAsync: vi.fn().mockResolvedValue(resolved), isPending: false };
}

let createChartM: ReturnType<typeof mutation>;
let createDashboardM: ReturnType<typeof mutation>;
let addTileM: ReturnType<typeof mutation>;

beforeEach(() => {
  createChartM = mutation({ id: "chart-1", name: "Total by region" });
  createDashboardM = mutation({ id: "dash-1", name: "My dashboard" });
  addTileM = mutation({ id: "tile-1" });
  // @ts-expect-error partial mock
  mockDashboards.mockReturnValue({ data: [] });
  // @ts-expect-error partial mock
  mockCreateChart.mockReturnValue(createChartM);
  // @ts-expect-error partial mock
  mockCreateDashboard.mockReturnValue(createDashboardM);
  // @ts-expect-error partial mock
  mockAddTile.mockReturnValue(addTileM);
});

afterEach(() => vi.clearAllMocks());

describe("AddToDashboard", () => {
  it("creates chart → dashboard → tile and derives the semantic source", async () => {
    render(
      <MemoryRouter>
        <AddToDashboard spec={spec} title="Total by region" />
      </MemoryRouter>
    );

    fireEvent.click(screen.getByRole("button", { name: /add to dashboard/i }));
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(addTileM.mutateAsync).toHaveBeenCalled());

    expect(createChartM.mutateAsync).toHaveBeenCalledWith({
      name: "Total by region",
      spec,
      source_kind: "semantic",
      source_ref: "regional_sales",
    });
    expect(createDashboardM.mutateAsync).toHaveBeenCalledWith({ name: "My dashboard" });
    expect(addTileM.mutateAsync).toHaveBeenCalledWith({
      dashboardId: "dash-1",
      tile: { chart_id: "chart-1", title: "Total by region" },
    });
    expect(toast.success).toHaveBeenCalled();
  });
});
