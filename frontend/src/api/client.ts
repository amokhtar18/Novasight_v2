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
import type {
  DatasetRead,
  NLChartRequest,
  NLChartResponse,
  QueryRequest,
  QueryResponse,
} from "@/types/api";

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

// ---------------------------------------------------------------------------
// NL→chart endpoint — POST /api/v1/ai/chart (Task 4.4)
// ---------------------------------------------------------------------------

/**
 * Discriminated error for the NL→chart endpoint.
 *
 * - `"ungroundable"` — 422: the spec could not be generated or validated;
 *   the caller should fall back to the manual builder.
 * - `"service_unavailable"` — 503: the LLM or Cube is temporarily down;
 *   transient, show a retry prompt.
 *
 * Any other non-2xx status is thrown as a plain `Error` (not `NLChartError`),
 * handled by the caller's generic error branch.
 */
export type NLChartErrorKind = "ungroundable" | "service_unavailable";

export class NLChartError extends Error {
  readonly kind: NLChartErrorKind;
  constructor(kind: NLChartErrorKind, message: string) {
    super(message);
    this.name = "NLChartError";
    this.kind = kind;
  }
}

/**
 * POST /api/v1/ai/chart — submit a natural-language chart description.
 *
 * Returns `NLChartResponse` on success.
 * Throws `NLChartError` on 422 (ungroundable) or 503 (service unavailable).
 * Throws a plain `Error` for other non-2xx statuses.
 */
export async function postNLChart(
  request: NLChartRequest
): Promise<NLChartResponse> {
  const response = await fetch(url("/ai/chart"), {
    method: "POST",
    headers: buildHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) detail = String(body.detail);
    } catch {
      // ignore — not JSON
    }

    if (response.status === 422) {
      throw new NLChartError("ungroundable", detail);
    }
    if (response.status === 503) {
      throw new NLChartError("service_unavailable", detail);
    }
    throw new Error(`API ${response.status}: ${detail}`);
  }

  return response.json() as Promise<NLChartResponse>;
}
