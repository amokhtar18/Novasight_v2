/**
 * Tests for DashboardCardTile — tiles re-run their saved chart's query (#10).
 *
 * useChartData, the tile mutation hooks, dnd-kit, and ChartRenderer are mocked so
 * the test focuses on the tile wiring: it resolves the embedded chart's spec via
 * useChartData and renders the chart with the tile's title.
 *
 * Native filters (Slice C): filters/selections are passed as NativeFilter[] +
 * FilterSelections; resolveTileFilters builds the appliedFilters forwarded to
 * useChartData. Cross-filter is a SemanticFilter overlay.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import type {
  ChartSpec,
  DashboardTileRead,
  NativeFilter,
  QueryResponse,
  SemanticFilter,
} from "@/types/api";
import type { FilterSelections } from "@/lib/dashboardFilters";

vi.mock("@/lib/useChartData", () => ({ useChartData: vi.fn() }));
vi.mock("@/api/hooks", () => ({
  useUpdateDashboardTile: vi.fn(() => ({ mutate: vi.fn() })),
  useDeleteDashboardTile: vi.fn(() => ({ mutate: vi.fn() })),
}));
vi.mock("@dnd-kit/sortable", () => ({
  useSortable: () => ({
    attributes: {},
    listeners: {},
    setNodeRef: vi.fn(),
    transform: null,
    transition: undefined,
    isDragging: false,
  }),
}));
vi.mock("@dnd-kit/utilities", () => ({ CSS: { Transform: { toString: () => "" } } }));
vi.mock("@/components/chart/ChartRenderer", () => ({
  ChartRenderer: ({
    title,
    onSelectCategory,
  }: {
    title?: string;
    onSelectCategory?: (c: string) => void;
  }) => (
    <div role="img" aria-label={title ?? "chart"} data-testid="chart-renderer">
      {onSelectCategory && (
        <button type="button" onClick={() => onSelectCategory("west")}>
          point
        </button>
      )}
    </div>
  ),
}));

import { DashboardCardTile } from "@/components/dashboard/DashboardCardTile";
import { useChartData } from "@/lib/useChartData";

const mockUseChartData = vi.mocked(useChartData);

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

const tile: DashboardTileRead = {
  id: "tile-1",
  kind: "chart",
  chart_id: "chart-1",
  content: null,
  title: "Region totals",
  position: 0,
  x: 0,
  y: 0,
  w: 6,
  h: 4,
  chart: {
    id: "chart-1",
    name: "Total by region",
    spec,
    source_kind: "semantic",
    source_ref: "regional_sales",
    owner_id: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
};

const data: QueryResponse = {
  columns: ["regional_sales.region", "regional_sales.total_amount"],
  rows: [["west", 100]],
  row_count: 1,
};

beforeEach(() => {
  // @ts-expect-error partial mock
  mockUseChartData.mockReturnValue({ data, isLoading: false, isError: false });
});

afterEach(() => vi.clearAllMocks());

/** A NativeFilter that targets the same cube as the tile. */
const sameCubeFilter: NativeFilter = {
  id: "f1",
  kind: "value",
  member: "regional_sales.region",
  operator: "equals",
  default_values: ["west"],
};
const sameCubeSelections: FilterSelections = {
  f1: { kind: "value", values: ["west"] },
};

/** A NativeFilter on a different cube — must not be applied. */
const otherCubeFilter: NativeFilter = {
  id: "f2",
  kind: "value",
  member: "orders.status",
  operator: "equals",
  default_values: ["paid"],
};
const otherCubeSelections: FilterSelections = {
  f2: { kind: "value", values: ["paid"] },
};

/** A SemanticFilter for cross-filter tests. */
const crossFilterSameCube: SemanticFilter = {
  member: "regional_sales.region",
  operator: "equals",
  values: ["east"],
};

describe("DashboardCardTile", () => {
  it("re-runs the chart's query and renders it with the tile title", () => {
    render(<DashboardCardTile tile={tile} dashboardId="dash-1" editing={false} />);

    expect(mockUseChartData).toHaveBeenCalledWith(spec, undefined, undefined);
    expect(screen.getByRole("img", { name: /region totals/i })).toBeInTheDocument();
  });

  it("falls back to the chart name when the tile has no title override", () => {
    const untitled = { ...tile, title: null };
    render(<DashboardCardTile tile={untitled} dashboardId="dash-1" editing={false} />);
    expect(screen.getByRole("img", { name: /total by region/i })).toBeInTheDocument();
  });

  it("applies the dashboard filter when it targets the tile's cube", () => {
    render(
      <DashboardCardTile
        tile={tile}
        dashboardId="dash-1"
        editing={false}
        filters={[sameCubeFilter]}
        selections={sameCubeSelections}
      />
    );
    const expectedFilter: SemanticFilter = {
      member: "regional_sales.region",
      operator: "equals",
      values: ["west"],
    };
    expect(mockUseChartData).toHaveBeenCalledWith(spec, [expectedFilter], undefined);
    expect(screen.getByText(/filtered/i)).toBeInTheDocument();
  });

  it("ignores a filter on a different cube", () => {
    render(
      <DashboardCardTile
        tile={tile}
        dashboardId="dash-1"
        editing={false}
        filters={[otherCubeFilter]}
        selections={otherCubeSelections}
      />
    );
    expect(mockUseChartData).toHaveBeenCalledWith(spec, undefined, undefined);
    expect(screen.queryByText(/filtered/i)).not.toBeInTheDocument();
  });

  it("cross-filters from a clicked category using the tile's dimension", () => {
    const onCrossFilter = vi.fn();
    render(
      <DashboardCardTile
        tile={tile}
        dashboardId="dash-1"
        editing={false}
        onCrossFilter={onCrossFilter}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "point" }));
    expect(onCrossFilter).toHaveBeenCalledWith("regional_sales.region", "west");
  });

  it("does not wire cross-filtering while editing", () => {
    const onCrossFilter = vi.fn();
    render(
      <DashboardCardTile
        tile={tile}
        dashboardId="dash-1"
        editing={true}
        onCrossFilter={onCrossFilter}
      />
    );
    expect(screen.queryByRole("button", { name: "point" })).not.toBeInTheDocument();
  });

  it("applies a cross-filter overlay when cube matches", () => {
    render(
      <DashboardCardTile
        tile={tile}
        dashboardId="dash-1"
        editing={false}
        crossFilter={crossFilterSameCube}
      />
    );
    expect(mockUseChartData).toHaveBeenCalledWith(spec, [crossFilterSameCube], undefined);
    expect(screen.getByText(/filtered/i)).toBeInTheDocument();
  });
});
