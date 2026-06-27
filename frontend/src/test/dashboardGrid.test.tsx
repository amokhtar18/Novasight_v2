import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { DashboardTileRead } from "@/types/api";

// Capture the gridstack stub + its event handlers so tests can drive "change".
const { gridStub, handlers, initSpy } = vi.hoisted(() => {
  const handlers: Record<string, (...a: unknown[]) => void> = {};
  const gridStub = {
    on: vi.fn((evt: string, cb: (...a: unknown[]) => void) => {
      handlers[evt] = cb;
    }),
    off: vi.fn(),
    save: vi.fn(() => [{ id: "t1", x: 0, y: 0, w: 6, h: 4 }]),
    destroy: vi.fn(),
    enableMove: vi.fn(),
    enableResize: vi.fn(),
    update: vi.fn(),
  };
  const initSpy = vi.fn(() => gridStub);
  return { gridStub, handlers, initSpy };
});

vi.mock("gridstack", () => ({ GridStack: { init: initSpy } }));

const mutate = vi.fn();
// Mock the whole hooks module so the real api client isn't imported. DashboardGrid
// only uses `useSetDashboardLayout` and `queryKeys.dashboard` from here.
vi.mock("@/api/hooks", () => ({
  useSetDashboardLayout: () => ({ mutate }),
  queryKeys: { dashboard: (id: string) => ["dashboards", id] as const },
}));

// Keep the test focused on grid wiring — stub the tile.
vi.mock("@/components/dashboard/DashboardCardTile", () => ({
  DashboardCardTile: ({ tile }: { tile: DashboardTileRead }) => (
    <div data-testid={`tile-${tile.id}`}>{tile.title}</div>
  ),
}));

import { DashboardGrid } from "@/components/dashboard/DashboardGrid";

function tile(id: string, x: number, y: number): DashboardTileRead {
  return {
    id, kind: "chart", chart_id: "c", content: null, title: id,
    position: 0, x, y, w: 6, h: 4, chart: null,
  };
}

function wrap(editing: boolean) {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <DashboardGrid
        tiles={[tile("t1", 0, 0)]}
        dashboardId="dash-1"
        editing={editing}
        filters={[]}
        selections={{}}
        crossFilter={[]}
      />
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  for (const k of Object.keys(handlers)) delete handlers[k];
});

describe("DashboardGrid (gridstack)", () => {
  it("renders each tile as a .grid-stack-item with gs-* attributes", () => {
    wrap(false);
    const item = screen.getByTestId("tile-t1").closest(".grid-stack-item");
    expect(item).not.toBeNull();
    expect(item).toHaveAttribute("gs-id", "t1");
    expect(item).toHaveAttribute("gs-w", "6");
  });

  it("initializes gridstack with a 12-column grid", () => {
    wrap(false);
    expect(initSpy).toHaveBeenCalledTimes(1);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect((initSpy.mock.calls as any)[0][0]).toMatchObject({ column: 12 });
  });

  it("enables drag/resize in edit mode and disables in view mode", () => {
    wrap(true);
    expect(gridStub.enableMove).toHaveBeenLastCalledWith(true);
    expect(gridStub.enableResize).toHaveBeenLastCalledWith(true);
  });

  it("persists the mapped layout (debounced) on a gridstack change", () => {
    vi.useFakeTimers();
    wrap(true);
    act(() => {
      handlers["change"]?.();
      vi.advanceTimersByTime(500);
    });
    expect(mutate).toHaveBeenCalledWith({
      tiles: [{ id: "t1", position: 0, x: 0, y: 0, w: 6, h: 4 }],
    });
    vi.useRealTimers();
  });

  it("tears down gridstack on unmount", () => {
    const { unmount } = wrap(false);
    unmount();
    expect(gridStub.destroy).toHaveBeenCalled();
  });
});
