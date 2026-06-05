/**
 * Typed API client for the Analytica backend.
 *
 * All server state goes through this module + TanStack Query.
 * No fetching logic in components.
 *
 * The base URL and auth token are read from runtime config at call time,
 * so they are never baked into the bundle.
 */

import { loadConfig } from "@/lib/config";
import type { DatasetRead, QueryRequest, QueryResponse } from "@/types/api";

/** Build request headers, injecting the Bearer token from runtime config. */
function buildHeaders(extra?: Record<string, string>): Headers {
  const { authToken } = loadConfig();
  const headers = new Headers({
    Authorization: `Bearer ${authToken}`,
    ...extra,
  });
  return headers;
}

/** Resolve the full URL for a path segment. */
function url(path: string): string {
  const { apiBaseUrl } = loadConfig();
  // Strip trailing slash from base, ensure leading slash on path.
  const base = apiBaseUrl.replace(/\/$/, "");
  const segment = path.startsWith("/") ? path : `/${path}`;
  return `${base}${segment}`;
}

/**
 * Generic JSON fetch helper.
 * Throws an Error with the HTTP status text for non-2xx responses.
 * Treats all API responses as untrusted — callers must validate with Zod
 * or type-guard before use if strict validation is needed.
 */
async function apiFetch<T>(
  endpoint: string,
  init?: RequestInit
): Promise<T> {
  const response = await fetch(url(endpoint), init);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) detail = String(body.detail);
    } catch {
      // ignore — not JSON
    }
    throw new Error(`API ${response.status}: ${detail}`);
  }
  return response.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Dataset endpoints
// ---------------------------------------------------------------------------

/** Upload a CSV file. Returns the created DatasetRead. */
export async function uploadDataset(file: File): Promise<DatasetRead> {
  const form = new FormData();
  form.append("file", file);
  // Do NOT set Content-Type — let the browser set multipart/form-data with boundary.
  return apiFetch<DatasetRead>("/datasets/upload", {
    method: "POST",
    headers: buildHeaders(),
    body: form,
  });
}

/** List all datasets for the current tenant. */
export async function listDatasets(): Promise<DatasetRead[]> {
  return apiFetch<DatasetRead[]>("/datasets", {
    headers: buildHeaders({ Accept: "application/json" }),
  });
}

/** Run a structured aggregation query against a dataset. */
export async function queryDataset(
  datasetId: string,
  request: QueryRequest
): Promise<QueryResponse> {
  return apiFetch<QueryResponse>(`/datasets/${datasetId}/query`, {
    method: "POST",
    headers: buildHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(request),
  });
}
