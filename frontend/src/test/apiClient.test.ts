/**
 * Unit tests for the API client.
 *
 * Verifies that:
 *  1. The Authorization header contains the Bearer token from runtime config.
 *  2. The correct URL (base URL + path) is constructed.
 *  3. Non-2xx responses throw an Error with the status code.
 */

import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { _resetConfig } from "@/lib/config";

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

// Inject a test config before any import of the API client.
function setWindowConfig(apiBaseUrl: string, authToken: string) {
  window.__APP_CONFIG__ = { apiBaseUrl, authToken };
}

beforeEach(() => {
  _resetConfig();
  setWindowConfig("/api/v1", "test-token-abc");
});

afterEach(() => {
  vi.restoreAllMocks();
  delete window.__APP_CONFIG__;
  _resetConfig();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("uploadDataset", () => {
  it("sends Authorization: Bearer <token> header", async () => {
    const mockFetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          id: "550e8400-e29b-41d4-a716-446655440000",
          name: "test",
          original_filename: "test.csv",
          content_type: "text/csv",
          size_bytes: 100,
          status: "pending",
          created_at: "2024-01-01T00:00:00Z",
        }),
        { status: 201, headers: { "Content-Type": "application/json" } }
      )
    );
    vi.stubGlobal("fetch", mockFetch);

    const { uploadDataset } = await import("@/api/client");
    const file = new File(["a,b\n1,2"], "test.csv", { type: "text/csv" });
    await uploadDataset(file);

    const [calledUrl, calledInit] = mockFetch.mock.calls[0] as [
      string,
      RequestInit,
    ];
    expect(calledUrl).toBe("/api/v1/datasets/upload");

    const headers = calledInit.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer test-token-abc");
  });

  it("throws an Error on non-2xx response", async () => {
    const mockFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "File too large" }), {
        status: 413,
        headers: { "Content-Type": "application/json" },
      })
    );
    vi.stubGlobal("fetch", mockFetch);

    const { uploadDataset } = await import("@/api/client");
    const file = new File(["data"], "big.csv", { type: "text/csv" });
    await expect(uploadDataset(file)).rejects.toThrow("413");
  });
});

describe("queryDataset", () => {
  it("sends POST with JSON body and Authorization header", async () => {
    const mockFetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ columns: ["cat", "count"], rows: [], row_count: 0 }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      )
    );
    vi.stubGlobal("fetch", mockFetch);

    const { queryDataset } = await import("@/api/client");
    await queryDataset("some-uuid", {
      dimensions: ["cat"],
      metrics: [{ function: "count" }],
    });

    const [calledUrl, calledInit] = mockFetch.mock.calls[0] as [
      string,
      RequestInit,
    ];
    expect(calledUrl).toBe("/api/v1/datasets/some-uuid/query");
    expect(calledInit.method).toBe("POST");

    const headers = calledInit.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer test-token-abc");

    const body = JSON.parse(calledInit.body as string) as unknown;
    expect(body).toMatchObject({
      dimensions: ["cat"],
      metrics: [{ function: "count" }],
    });
  });
});
