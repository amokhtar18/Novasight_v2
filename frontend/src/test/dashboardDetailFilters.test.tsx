/**
 * Tests for DashboardDetail's filter persistence wiring (dashboard filters slice 3).
 *
 * useDashboard/useUpdateDashboard and the grid + filter bar are mocked so the test
 * focuses on: the active filter initialises from the dashboard's persisted filters,
 * and changing it persists via updateDashboard (patch.filters).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import type { DashboardRead } from "@/types/api";

vi.mock("react-router-dom", () => ({
  useParams: () => ({ dashboardId: "dash-1" }),
  Link: ({ children }: { children: React.ReactNode }) => <a>{children}</a>,
}));
vi.mock("@/api/hooks", () => ({
  useDashboard: vi.fn(),
  useUpdateDashboard: vi.fn(),
}));
vi.mock("@/components/dashboard/DashboardGrid", () => ({
  DashboardGrid: ({
    onCrossFilter,
  }: {
    onCrossFilter?: (member: string, value: string) => void;
  }) => (
    <div data-testid="grid">
      {onCrossFilter && (
        <button onClick={() => onCrossFilter("regional_sales.region", "west")}>cross</button>
      )}
    </div>
  ),
}));
vi.mock("@/components/dashboard/DashboardFilterBar", () => ({
  DashboardFilterBar: ({
    value,
    onChange,
  }: {
    value: { member: string } | null;
    onChange: (f: unknown) => void;
  }) => (
    <div>
      <span data-testid="active-member">{value?.member ?? "none"}</span>
      <button
        onClick={() =>
          onChange({ member: "regional_sales.region", operator: "equals", values: ["west"] })
        }
      >
        set-filter
      </button>
      <button onClick={() => onChange(null)}>clear-filter</button>
    </div>
  ),
}));

import { DashboardDetail } from "@/pages/DashboardDetail";
import { useDashboard, useUpdateDashboard } from "@/api/hooks";

const tile = {
  id: "t1",
  chart_id: "c1",
  title: "T",
  position: 0,
  x: 0,
  y: 0,
  w: 6,
  h: 4,
  chart: {
    id: "c1",
    name: "Chart",
    spec: { version: "1", type: "bar", query: {}, encoding: { series: [{ field: "x" }] } },
    source_kind: "semantic",
    source_ref: "regional_sales",
    owner_id: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
} as unknown as DashboardRead["tiles"][number];

function board(filters: DashboardRead["filters"] = []): DashboardRead {
  return {
    id: "dash-1",
    name: "Sales",
    description: null,
    owner_id: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    filters,
    tiles: [tile],
  };
}

let mutate: ReturnType<typeof vi.fn>;

beforeEach(() => {
  mutate = vi.fn();
  // @ts-expect-error partial mock
  vi.mocked(useUpdateDashboard).mockReturnValue({ mutate });
});

afterEach(() => vi.clearAllMocks());

describe("DashboardDetail filter persistence", () => {
  it("initialises the active filter from the dashboard's persisted filters", () => {
    // @ts-expect-error partial mock
    vi.mocked(useDashboard).mockReturnValue({
      data: board([{ member: "regional_sales.region", operator: "equals", values: ["west"] }]),
      isLoading: false,
      isError: false,
    });
    render(<DashboardDetail />);
    expect(screen.getByTestId("active-member")).toHaveTextContent("regional_sales.region");
  });

  it("persists a filter change via updateDashboard", () => {
    // @ts-expect-error partial mock
    vi.mocked(useDashboard).mockReturnValue({ data: board(), isLoading: false, isError: false });
    render(<DashboardDetail />);

    fireEvent.click(screen.getByText("set-filter"));
    expect(mutate).toHaveBeenCalledWith({
      id: "dash-1",
      patch: {
        filters: [{ member: "regional_sales.region", operator: "equals", values: ["west"] }],
      },
    });

    fireEvent.click(screen.getByText("clear-filter"));
    expect(mutate).toHaveBeenLastCalledWith({ id: "dash-1", patch: { filters: [] } });
  });

  it("persists a cross-filter from a clicked chart point", () => {
    // @ts-expect-error partial mock
    vi.mocked(useDashboard).mockReturnValue({ data: board(), isLoading: false, isError: false });
    render(<DashboardDetail />);

    fireEvent.click(screen.getByText("cross"));
    expect(mutate).toHaveBeenLastCalledWith({
      id: "dash-1",
      patch: {
        filters: [{ member: "regional_sales.region", operator: "equals", values: ["west"] }],
      },
    });
  });
});
