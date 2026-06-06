/**
 * Unit tests for the auth store: session lifecycle + the isAuthenticated helper.
 */

import { describe, it, expect, beforeEach } from "vitest";
import { useAuthStore, isAuthenticated } from "@/store/authStore";

const SESSION = {
  accessToken: "access-1",
  refreshToken: "refresh-1",
  user: {
    id: "u1",
    email: "u@example.com",
    name: "User One",
    tenant: "local",
    roles: ["superuser"],
  },
};

beforeEach(() => {
  useAuthStore.getState().clear();
});

describe("authStore", () => {
  it("starts unauthenticated", () => {
    expect(isAuthenticated()).toBe(false);
    expect(useAuthStore.getState().user).toBeNull();
  });

  it("records a session on setSession", () => {
    useAuthStore.getState().setSession(SESSION);
    expect(isAuthenticated()).toBe(true);
    expect(useAuthStore.getState().accessToken).toBe("access-1");
    expect(useAuthStore.getState().user?.roles).toEqual(["superuser"]);
  });

  it("replaces only the access token on setAccessToken", () => {
    useAuthStore.getState().setSession(SESSION);
    useAuthStore.getState().setAccessToken("access-2");
    expect(useAuthStore.getState().accessToken).toBe("access-2");
    // refresh token + user are preserved across a silent refresh
    expect(useAuthStore.getState().refreshToken).toBe("refresh-1");
    expect(useAuthStore.getState().user?.email).toBe("u@example.com");
  });

  it("clears the session on clear", () => {
    useAuthStore.getState().setSession(SESSION);
    useAuthStore.getState().clear();
    expect(isAuthenticated()).toBe(false);
    expect(useAuthStore.getState().refreshToken).toBeNull();
    expect(useAuthStore.getState().user).toBeNull();
  });
});
