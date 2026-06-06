/**
 * Typed API client for the NovaSight backend.
 *
 * All server state goes through this module + TanStack Query. No fetching logic
 * in components.
 *
 * Auth: the access token is read from the auth store at call time and sent as a
 * Bearer header. On a 401 the client transparently refreshes the token once and
 * retries; if the refresh fails it clears the session (the app then redirects to
 * the login screen). The base URL comes from runtime config — never baked in.
 */

import { loadConfig } from "@/lib/config";
import { useAuthStore } from "@/store/authStore";
import type {
  AccessTokenResponse,
  DatasetRead,
  HealthRead,
  InsightRequest,
  InsightResponse,
  LoginRequest,
  MeRead,
  NLChartRequest,
  NLChartResponse,
  NLQueryRequest,
  NLQueryResponse,
  QueryRequest,
  QueryResponse,
  SuggestionsResponse,
  TenantProvisionRequest,
  TenantRead,
  TokenResponse,
  UserCreate,
  UserRead,
  UserUpdate,
} from "@/types/api";

/** Resolve the full URL for a path segment. */
function url(path: string): string {
  const { apiBaseUrl } = loadConfig();
  const base = apiBaseUrl.replace(/\/$/, "");
  const segment = path.startsWith("/") ? path : `/${path}`;
  return `${base}${segment}`;
}

// ---------------------------------------------------------------------------
// Auth-aware fetch with single-flight token refresh
// ---------------------------------------------------------------------------

let refreshInFlight: Promise<boolean> | null = null;

async function attemptRefresh(): Promise<boolean> {
  const { refreshToken } = useAuthStore.getState();
  if (!refreshToken) return false;
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        const res = await fetch(url("/auth/refresh"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: refreshToken }),
        });
        if (!res.ok) return false;
        const data = (await res.json()) as AccessTokenResponse;
        useAuthStore.getState().setAccessToken(data.access_token);
        return true;
      } catch {
        return false;
      } finally {
        refreshInFlight = null;
      }
    })();
  }
  return refreshInFlight;
}

/** Build headers with the current access token + any extra headers. */
function authHeaders(extra: Record<string, string> = {}): Headers {
  const headers = new Headers(extra);
  const token = useAuthStore.getState().accessToken;
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return headers;
}

/**
 * Fetch with the access token attached; on 401, refresh once and retry, or clear
 * the session if the refresh fails.
 */
async function fetchWithAuth(
  endpoint: string,
  init: RequestInit = {},
  extra: Record<string, string> = {}
): Promise<Response> {
  let res = await fetch(url(endpoint), { ...init, headers: authHeaders(extra) });
  if (res.status === 401 && useAuthStore.getState().refreshToken) {
    if (await attemptRefresh()) {
      res = await fetch(url(endpoint), { ...init, headers: authHeaders(extra) });
    } else {
      useAuthStore.getState().clear();
    }
  }
  return res;
}

async function parseDetail(response: Response): Promise<string> {
  let detail = response.statusText;
  try {
    const body = (await response.json()) as { detail?: string };
    if (body.detail) detail = String(body.detail);
  } catch {
    // not JSON
  }
  return detail;
}

/** Generic JSON fetch helper (auth-aware). Throws on non-2xx. */
async function apiFetch<T>(
  endpoint: string,
  init: RequestInit = {},
  extra: Record<string, string> = {}
): Promise<T> {
  const response = await fetchWithAuth(endpoint, init, extra);
  if (!response.ok) {
    throw new Error(`API ${response.status}: ${await parseDetail(response)}`);
  }
  return response.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Auth endpoints (no bearer token required)
// ---------------------------------------------------------------------------

/** POST /auth/login — exchange credentials for tokens + identity. */
export async function login(request: LoginRequest): Promise<TokenResponse> {
  const res = await fetch(url("/auth/login"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    throw new Error(`API ${res.status}: ${await parseDetail(res)}`);
  }
  return res.json() as Promise<TokenResponse>;
}

/** POST /auth/logout — stateless; best-effort server notification. */
export async function logout(): Promise<void> {
  try {
    await fetchWithAuth("/auth/logout", { method: "POST" });
  } catch {
    // ignore — logout is client-side regardless
  }
}

// ---------------------------------------------------------------------------
// Dataset endpoints
// ---------------------------------------------------------------------------

/** Upload a CSV file. Returns the created DatasetRead. */
export async function uploadDataset(file: File): Promise<DatasetRead> {
  const form = new FormData();
  form.append("file", file);
  // No Content-Type — the browser sets multipart/form-data with the boundary.
  return apiFetch<DatasetRead>("/datasets/upload", { method: "POST", body: form });
}

/** List all datasets for the current tenant. */
export async function listDatasets(): Promise<DatasetRead[]> {
  return apiFetch<DatasetRead[]>("/datasets", {}, { Accept: "application/json" });
}

/** Run a structured aggregation query against a dataset. */
export async function queryDataset(
  datasetId: string,
  request: QueryRequest
): Promise<QueryResponse> {
  return apiFetch<QueryResponse>(
    `/datasets/${datasetId}/query`,
    { method: "POST", body: JSON.stringify(request) },
    { "Content-Type": "application/json" }
  );
}

// ---------------------------------------------------------------------------
// Identity + health
// ---------------------------------------------------------------------------

/** Resolved tenant context + verified identity for the authenticated caller. */
export async function getMe(): Promise<MeRead> {
  return apiFetch<MeRead>("/me", {}, { Accept: "application/json" });
}

/**
 * Component health. A 503 here is a *valid* "degraded" payload, so we read the
 * JSON body regardless of status and only throw when it is not the expected shape.
 */
export async function getHealth(): Promise<HealthRead> {
  const response = await fetchWithAuth("/health", {}, { Accept: "application/json" });
  try {
    const body = (await response.json()) as HealthRead;
    if (body && Array.isArray(body.components)) return body;
  } catch {
    // fall through
  }
  throw new Error(`API ${response.status}: ${response.statusText}`);
}

// ---------------------------------------------------------------------------
// AI: NL→SQL, insights, suggestions
// ---------------------------------------------------------------------------

/** POST /ai/query — translate a question to validated SQL and execute it. */
export async function postNLQuery(request: NLQueryRequest): Promise<NLQueryResponse> {
  return apiFetch<NLQueryResponse>(
    "/ai/query",
    { method: "POST", body: JSON.stringify(request) },
    { "Content-Type": "application/json" }
  );
}

/** POST /ai/insights — summarise an already-computed result set. */
export async function postInsight(request: InsightRequest): Promise<InsightResponse> {
  return apiFetch<InsightResponse>(
    "/ai/insights",
    { method: "POST", body: JSON.stringify(request) },
    { "Content-Type": "application/json" }
  );
}

/** POST /ai/datasets/{id}/suggestions — validated chart suggestions. */
export async function getSuggestions(datasetId: string): Promise<SuggestionsResponse> {
  return apiFetch<SuggestionsResponse>(
    `/ai/datasets/${datasetId}/suggestions`,
    { method: "POST" },
    { "Content-Type": "application/json" }
  );
}

// ---------------------------------------------------------------------------
// Control plane: tenants (platform admin)
// ---------------------------------------------------------------------------

/** GET /tenants — list all tenants. */
export async function listTenants(): Promise<TenantRead[]> {
  return apiFetch<TenantRead[]>("/tenants", {}, { Accept: "application/json" });
}

/** POST /tenants — provision a new isolated tenant. */
export async function provisionTenant(
  request: TenantProvisionRequest
): Promise<TenantRead> {
  return apiFetch<TenantRead>(
    "/tenants",
    { method: "POST", body: JSON.stringify(request) },
    { "Content-Type": "application/json" }
  );
}

/** DELETE /tenants/{slug} — de-provision a tenant. */
export async function deprovisionTenant(slug: string): Promise<void> {
  const response = await fetchWithAuth(`/tenants/${slug}`, { method: "DELETE" });
  if (!response.ok) {
    throw new Error(`API ${response.status}: ${await parseDetail(response)}`);
  }
}

// ---------------------------------------------------------------------------
// User management (tenant superuser)
// ---------------------------------------------------------------------------

/** GET /users — list the tenant's users. */
export async function listUsers(): Promise<UserRead[]> {
  return apiFetch<UserRead[]>("/users", {}, { Accept: "application/json" });
}

/** POST /users — create a user in the caller's tenant. */
export async function createUser(request: UserCreate): Promise<UserRead> {
  return apiFetch<UserRead>(
    "/users",
    { method: "POST", body: JSON.stringify(request) },
    { "Content-Type": "application/json" }
  );
}

/** PATCH /users/{id} — partial update. */
export async function updateUser(id: string, request: UserUpdate): Promise<UserRead> {
  return apiFetch<UserRead>(
    `/users/${id}`,
    { method: "PATCH", body: JSON.stringify(request) },
    { "Content-Type": "application/json" }
  );
}

/** DELETE /users/{id}. */
export async function deleteUser(id: string): Promise<void> {
  const response = await fetchWithAuth(`/users/${id}`, { method: "DELETE" });
  if (!response.ok) {
    throw new Error(`API ${response.status}: ${await parseDetail(response)}`);
  }
}

// ---------------------------------------------------------------------------
// NL→chart endpoint — POST /api/v1/ai/chart
// ---------------------------------------------------------------------------

/**
 * Discriminated error for the NL→chart endpoint.
 * - "ungroundable" (422): spec could not be generated/validated → manual fallback.
 * - "service_unavailable" (503): LLM/Cube temporarily down → retry.
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

/** POST /api/v1/ai/chart — submit a natural-language chart description. */
export async function postNLChart(request: NLChartRequest): Promise<NLChartResponse> {
  const response = await fetchWithAuth(
    "/ai/chart",
    { method: "POST", body: JSON.stringify(request) },
    { "Content-Type": "application/json" }
  );
  if (!response.ok) {
    const detail = await parseDetail(response);
    if (response.status === 422) throw new NLChartError("ungroundable", detail);
    if (response.status === 503) throw new NLChartError("service_unavailable", detail);
    throw new Error(`API ${response.status}: ${detail}`);
  }
  return response.json() as Promise<NLChartResponse>;
}
