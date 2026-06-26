// frontend/src/test/dashboardDetailFilters.test.tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { DashboardDetail } from "@/pages/DashboardDetail";

// ---------------------------------------------------------------------------
// Shared board fixtures
// ---------------------------------------------------------------------------
const boardWithFilter = {
  id: "d1", name: "Board", description: null, owner_id: null,
  created_at: "", updated_at: "",
  native_filters: [{ id: "f1", kind: "value", member: "regional_sales.region", operator: "equals", label: "Region" }],
  tiles: [{
    id: "t1", kind: "chart", chart_id: "c", content: null, title: "Sales", position: 0, x: 0, y: 0, w: 6, h: 4,
    chart: { id: "c", name: "Sales", source_kind: "semantic", source_ref: null, owner_id: null, created_at: "", updated_at: "",
      spec: { type: "bar", query: { metric_refs: ["regional_sales.total_amount"] }, encoding: { x: "regional_sales.region", series: [{ field: "regional_sales.total_amount" }] } } },
  }],
};

const boardNoFilters = {
  ...boardWithFilter,
  id: "d2",
  native_filters: [],
};

// ---------------------------------------------------------------------------
// Mutable board reference — tests can point this at any fixture before render.
// ---------------------------------------------------------------------------
let activeBoard: typeof boardWithFilter = boardWithFilter;

vi.mock("@/api/hooks", async () => {
  const actual = await vi.importActual<typeof import("@/api/hooks")>("@/api/hooks");
  return {
    ...actual,
    useDashboard: () => ({ data: activeBoard, isLoading: false, isError: false }),
    useUpdateDashboard: () => ({ mutate: vi.fn() }),
    useAddDashboardTile: () => ({ mutate: vi.fn() }),
    useSemanticValues: () => ({ data: { values: ["west", "east"] }, isLoading: false }),
    useDeleteDashboardTile: () => ({ mutate: vi.fn() }),
    useUpdateDashboardTile: () => ({ mutate: vi.fn() }),
    useSetDashboardLayout: () => ({ mutate: vi.fn() }),
  };
});
vi.mock("@/lib/identity", () => ({ useIdentity: () => ({ canEdit: true }) }));
vi.mock("@/lib/useChartData", () => ({ useChartData: vi.fn(() => ({ data: { columns: [], rows: [], row_count: 0 }, isLoading: false, isError: false })) }));

// ChartRenderer mock — mirrors dashboardCardTile.test.tsx: exposes an "onSelectPoints"
// button so integration tests can trigger a cross-filter emission.
vi.mock("@/components/chart/ChartRenderer", () => ({
  ChartRenderer: ({
    title,
    onSelectPoints,
  }: {
    title?: string;
    onSelectPoints?: (pairs: { member: string; value: string }[]) => void;
  }) => (
    <div role="img" aria-label={title ?? "chart"} data-testid="chart-renderer">
      {onSelectPoints && (
        <button type="button" onClick={() => onSelectPoints([{ member: "regional_sales.region", value: "west" }])}>
          point
        </button>
      )}
    </div>
  ),
}));

// dnd-kit stubs — DashboardGrid uses these; they must not throw in JSDOM.
vi.mock("@dnd-kit/core", () => ({
  DndContext: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  PointerSensor: class {},
  KeyboardSensor: class {},
  closestCenter: vi.fn(),
  useSensor: vi.fn(),
  useSensors: vi.fn(() => []),
}));
vi.mock("@dnd-kit/sortable", () => ({
  SortableContext: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  arrayMove: vi.fn(),
  rectSortingStrategy: vi.fn(),
  sortableKeyboardCoordinates: vi.fn(),
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

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------
function wrap(board = boardWithFilter) {
  activeBoard = board;
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/dashboards/${board.id}`]}>
        <Routes>
          <Route path="/dashboards/:dashboardId" element={<DashboardDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe("DashboardDetail native filters", () => {
  it("renders the native-filter drawer with the configured filter", () => {
    wrap(boardWithFilter);
    expect(screen.getByText("Region")).toBeInTheDocument();
  });

  it("shows Add filter button in edit mode even when native_filters is empty", async () => {
    const user = userEvent.setup();
    wrap(boardNoFilters);

    // Enter edit mode via the PageHeader "Edit" button
    await user.click(screen.getByRole("button", { name: /^edit$/i }));

    // The filter drawer must now be rendered and expose "Add filter"
    expect(screen.getByRole("button", { name: /add filter/i })).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// I3 — cross-filter wiring: handleCrossFilter(pairs) → SemanticFilter[] propagation
// ---------------------------------------------------------------------------

describe("DashboardDetail cross-filter wiring", () => {
  it("maps SelectionPair[] from a tile click to SemanticFilter[] and propagates it to tiles", async () => {
    const { useChartData } = await import("@/lib/useChartData");
    const mockUseChartData = vi.mocked(useChartData);

    // Return data with row_count > 0 so DashboardCardTile renders ChartRenderer
    // (which exposes the "point" button in its mock) rather than the "No data" empty state.
    mockUseChartData.mockReturnValue({
      data: { columns: ["regional_sales.region", "regional_sales.total_amount"], rows: [["west", 100]], row_count: 1 },
      isLoading: false,
      isError: false,
    } as ReturnType<typeof useChartData>);

    wrap(boardWithFilter);

    // The ChartRenderer mock renders a "point" button when onSelectPoints is wired.
    // Click it to emit: onSelectPoints([{ member: "regional_sales.region", value: "west" }])
    // DashboardDetail.handleCrossFilter maps that to SemanticFilter[]:
    //   [{ member: "regional_sales.region", operator: "equals", values: ["west"] }]
    // and propagates it down as crossFilter → DashboardGrid → DashboardCardTile → useChartData.
    fireEvent.click(screen.getByRole("button", { name: "point" }));

    // After the click, useChartData must have been called with the derived SemanticFilter.
    // DashboardCardTile merges cross-filter into appliedFilters and passes it as the
    // second argument: useChartData(spec, appliedFilters, dateRangeOverrides).
    const expectedFilter = [{ member: "regional_sales.region", operator: "equals", values: ["west"] }];
    const calls = mockUseChartData.mock.calls;
    const lastCall = calls[calls.length - 1];
    expect(lastCall[1]).toEqual(expectedFilter);

    // Reset so the mock doesn't bleed into other tests.
    mockUseChartData.mockReset();
    mockUseChartData.mockReturnValue({
      data: { columns: [], rows: [], row_count: 0 },
      isLoading: false,
      isError: false,
    } as unknown as ReturnType<typeof useChartData>);
  });
});
