/**
 * Zustand store for local UI state.
 *
 * Server state (datasets, query results) lives in TanStack Query.
 * This store holds only navigation/UI state that is not persisted.
 */

import { create } from "zustand";
import type { ChartSpec } from "@/types/api";

interface AppState {
  /** ID of the dataset selected for viewing after upload. */
  selectedDatasetId: string | null;
  /** Chart spec chosen for the results screen. */
  chartSpec: ChartSpec | null;

  setSelectedDataset: (id: string) => void;
  setChartSpec: (spec: ChartSpec) => void;
  reset: () => void;
}

const initialState = {
  selectedDatasetId: null as string | null,
  chartSpec: null as ChartSpec | null,
};

export const useAppStore = create<AppState>((set) => ({
  ...initialState,
  setSelectedDataset: (id) => set({ selectedDatasetId: id }),
  setChartSpec: (spec) => set({ chartSpec: spec }),
  reset: () => set(initialState),
}));
