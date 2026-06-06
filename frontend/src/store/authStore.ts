/**
 * Auth store — the single source of truth for the signed-in session.
 *
 * Holds the access + refresh tokens and the verified user identity, persisted to
 * localStorage so a reload keeps the session. The API client reads the access
 * token from here at call time (via `useAuthStore.getState()`), and refreshes or
 * clears it on a 401 — so there is no token baked into the bundle or config.js.
 *
 * Tokens live in localStorage (acceptable for the single-origin deployment); a
 * future hardening step can move them to httpOnly cookies behind the proxy.
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { UserIdentity } from "@/types/api";

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  user: UserIdentity | null;
  /** Record a fresh session (login). */
  setSession: (s: {
    accessToken: string;
    refreshToken: string;
    user: UserIdentity;
  }) => void;
  /** Replace just the access token (silent refresh). */
  setAccessToken: (token: string) => void;
  /** Clear the session (logout / failed refresh). */
  clear: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      refreshToken: null,
      user: null,
      setSession: ({ accessToken, refreshToken, user }) =>
        set({ accessToken, refreshToken, user }),
      setAccessToken: (accessToken) => set({ accessToken }),
      clear: () => set({ accessToken: null, refreshToken: null, user: null }),
    }),
    { name: "novasight.auth" }
  )
);

/** True when a session token is present. */
export function isAuthenticated(): boolean {
  return useAuthStore.getState().accessToken !== null;
}
