/**
 * Tests for the client-side dashboards store:
 *   - dashboards are partitioned per tenant (no cross-tenant leakage);
 *   - create / addItem / removeItem / reorder behave as expected;
 *   - state persists across a (simulated) reload via localStorage.
 */

import { describe, it, expect, beforeEach } from "vitest";
import { useDashboardsStore } from "@/store/dashboardsStore";
import type { ChartSpec } from "@/types/api";

const spec: ChartSpec = {
  version: "1",
  type: "bar",
  query: { dataset_id: "ds-1", query: { dimensions: ["c"], metrics: [{ function: "count", alias: "value" }] } },
  encoding: { x: "c", series: [{ field: "value" }] },
};

const A = "tenant-a";
const B = "tenant-b";

beforeEach(() => {
  localStorage.clear();
  useDashboardsStore.setState({ byTenant: {} });
});

describe("dashboardsStore — tenant isolation", () => {
  it("partitions dashboards per tenant", () => {
    const s = useDashboardsStore.getState();
    s.create(A, "A board");
    expect(useDashboardsStore.getState().list(A)).toHaveLength(1);
    expect(useDashboardsStore.getState().list(B)).toHaveLength(0);
  });
});

describe("dashboardsStore — items", () => {
  it("adds, finds, and removes items", () => {
    const s = useDashboardsStore.getState();
    const board = s.create(A, "Board");
    s.addItem(A, board.id, { title: "Chart 1", spec });

    let saved = useDashboardsStore.getState().get(A, board.id);
    expect(saved?.items).toHaveLength(1);
    expect(saved?.items[0].title).toBe("Chart 1");
    expect(saved?.items[0].size).toBe("md");

    const itemId = saved!.items[0].id;
    useDashboardsStore.getState().removeItem(A, board.id, itemId);
    saved = useDashboardsStore.getState().get(A, board.id);
    expect(saved?.items).toHaveLength(0);
  });

  it("reorders items via setItems", () => {
    const s = useDashboardsStore.getState();
    const board = s.create(A, "Board");
    s.addItem(A, board.id, { title: "one", spec });
    s.addItem(A, board.id, { title: "two", spec });

    const items = useDashboardsStore.getState().get(A, board.id)!.items;
    const reversed = [items[1], items[0]];
    useDashboardsStore.getState().setItems(A, board.id, reversed);

    const after = useDashboardsStore.getState().get(A, board.id)!.items;
    expect(after.map((i) => i.title)).toEqual(["two", "one"]);
  });

  it("changes a tile size", () => {
    const s = useDashboardsStore.getState();
    const board = s.create(A, "Board");
    s.addItem(A, board.id, { title: "one", spec });
    const itemId = useDashboardsStore.getState().get(A, board.id)!.items[0].id;
    useDashboardsStore.getState().setItemSize(A, board.id, itemId, "lg");
    expect(useDashboardsStore.getState().get(A, board.id)!.items[0].size).toBe("lg");
  });
});

describe("dashboardsStore — persistence", () => {
  it("writes to localStorage under the namespaced key", () => {
    useDashboardsStore.getState().create(A, "Persisted");
    const raw = localStorage.getItem("novasight.dashboards");
    expect(raw).toBeTruthy();
    expect(raw).toContain("Persisted");
  });
});
