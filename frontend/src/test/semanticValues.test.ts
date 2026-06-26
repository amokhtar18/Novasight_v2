import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import { _resetConfig } from "@/lib/config";
import { useAuthStore } from "@/store/authStore";
import { semanticValues } from "@/api/client";

beforeEach(() => {
  _resetConfig();
  window.__APP_CONFIG__ = { apiBaseUrl: "/api/v1" };
  useAuthStore.getState().setSession({
    accessToken: "test-token",
    refreshToken: "refresh-token",
    user: { id: "u1", email: "u@x", name: null, tenant: "local", roles: [] },
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  delete window.__APP_CONFIG__;
  _resetConfig();
  useAuthStore.getState().clear();
});

describe("semanticValues client", () => {
  it("POSTs to /semantic/values and returns values", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ values: ["west", "east"] }), {
        status: 200, headers: { "Content-Type": "application/json" },
      })
    );
    const out = await semanticValues({ member: "regional_sales.region", search: "we" });
    expect(out.values).toEqual(["west", "east"]);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/semantic/values");
    expect(JSON.parse(String(init?.body))).toMatchObject({ member: "regional_sales.region", search: "we" });
  });
});
