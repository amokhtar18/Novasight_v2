/**
 * UI/navigation state for the app shell (not server state, not persisted as
 * domain data). Holds the sidebar collapse + mobile drawer state.
 */

import { create } from "zustand";

interface UiState {
  /** Desktop: rail collapsed to icons only. */
  sidebarCollapsed: boolean;
  /** Mobile: drawer open. */
  mobileNavOpen: boolean;
  toggleSidebar: () => void;
  setMobileNav: (open: boolean) => void;
}

export const useUiStore = create<UiState>((set) => ({
  sidebarCollapsed: false,
  mobileNavOpen: false,
  toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
  setMobileNav: (open) => set({ mobileNavOpen: open }),
}));
