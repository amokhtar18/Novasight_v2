/**
 * Dashboards store — client-side persistence (localStorage) of user-built
 * dashboards, partitioned per tenant.
 *
 * There is no backend dashboard endpoint yet, so dashboards live in the browser.
 * State is partitioned by tenant id (resolved from the verified JWT via /me) so
 * one tenant never sees another's saved boards on a shared machine. The shape is
 * intentionally backend-friendly: when a persistence API lands, these actions can
 * be swapped to TanStack Query mutations behind the same call sites.
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { ChartSpec, QueryResponse } from "@/types/api";

export type TileSize = "sm" | "md" | "lg";

export interface DashboardItem {
  id: string;
  title: string;
  /** The full chart contract. */
  spec: ChartSpec;
  size: TileSize;
  /**
   * Optional captured result. Tiles whose spec is a re-runnable dataset query
   * omit this (they re-fetch live); AI/NL specs that can't be re-resolved
   * client-side carry a snapshot taken when the chart was saved.
   */
  data?: QueryResponse;
}

export interface Dashboard {
  id: string;
  name: string;
  createdAt: string;
  updatedAt: string;
  items: DashboardItem[];
}

interface DashboardsState {
  /** tenantId → that tenant's dashboards. */
  byTenant: Record<string, Dashboard[]>;
  list: (tenantId: string) => Dashboard[];
  get: (tenantId: string, id: string) => Dashboard | undefined;
  create: (tenantId: string, name: string) => Dashboard;
  rename: (tenantId: string, id: string, name: string) => void;
  remove: (tenantId: string, id: string) => void;
  addItem: (
    tenantId: string,
    dashboardId: string,
    item: { title: string; spec: ChartSpec; size?: TileSize; data?: QueryResponse }
  ) => void;
  removeItem: (tenantId: string, dashboardId: string, itemId: string) => void;
  setItems: (tenantId: string, dashboardId: string, items: DashboardItem[]) => void;
  setItemSize: (
    tenantId: string,
    dashboardId: string,
    itemId: string,
    size: TileSize
  ) => void;
}

/** Stable id generator (crypto.randomUUID with a small fallback for old envs). */
export function newId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `id-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

/** Immutably update one dashboard within a tenant's list. */
function updateBoard(
  state: DashboardsState,
  tenantId: string,
  dashboardId: string,
  fn: (d: Dashboard) => Dashboard
): Record<string, Dashboard[]> {
  const boards = state.byTenant[tenantId] ?? [];
  return {
    ...state.byTenant,
    [tenantId]: boards.map((d) =>
      d.id === dashboardId ? { ...fn(d), updatedAt: new Date().toISOString() } : d
    ),
  };
}

export const useDashboardsStore = create<DashboardsState>()(
  persist(
    (set, get) => ({
      byTenant: {},

      list: (tenantId) => get().byTenant[tenantId] ?? [],

      get: (tenantId, id) =>
        (get().byTenant[tenantId] ?? []).find((d) => d.id === id),

      create: (tenantId, name) => {
        const now = new Date().toISOString();
        const board: Dashboard = {
          id: newId(),
          name: name.trim() || "Untitled dashboard",
          createdAt: now,
          updatedAt: now,
          items: [],
        };
        set((state) => ({
          byTenant: {
            ...state.byTenant,
            [tenantId]: [board, ...(state.byTenant[tenantId] ?? [])],
          },
        }));
        return board;
      },

      rename: (tenantId, id, name) =>
        set((state) => ({
          byTenant: updateBoard(state, tenantId, id, (d) => ({
            ...d,
            name: name.trim() || d.name,
          })),
        })),

      remove: (tenantId, id) =>
        set((state) => ({
          byTenant: {
            ...state.byTenant,
            [tenantId]: (state.byTenant[tenantId] ?? []).filter((d) => d.id !== id),
          },
        })),

      addItem: (tenantId, dashboardId, item) =>
        set((state) => ({
          byTenant: updateBoard(state, tenantId, dashboardId, (d) => ({
            ...d,
            items: [
              ...d.items,
              {
                id: newId(),
                title: item.title,
                spec: item.spec,
                size: item.size ?? "md",
                data: item.data,
              },
            ],
          })),
        })),

      removeItem: (tenantId, dashboardId, itemId) =>
        set((state) => ({
          byTenant: updateBoard(state, tenantId, dashboardId, (d) => ({
            ...d,
            items: d.items.filter((i) => i.id !== itemId),
          })),
        })),

      setItems: (tenantId, dashboardId, items) =>
        set((state) => ({
          byTenant: updateBoard(state, tenantId, dashboardId, (d) => ({
            ...d,
            items,
          })),
        })),

      setItemSize: (tenantId, dashboardId, itemId, size) =>
        set((state) => ({
          byTenant: updateBoard(state, tenantId, dashboardId, (d) => ({
            ...d,
            items: d.items.map((i) => (i.id === itemId ? { ...i, size } : i)),
          })),
        })),
    }),
    { name: "novasight.dashboards" }
  )
);
