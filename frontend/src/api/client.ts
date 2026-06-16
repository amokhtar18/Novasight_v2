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
  ChartCreate,
  ChatRequest,
  ChatResponse,
  DashboardCreate,
  DbtModelDefCreate,
  DbtModelDefRead,
  DbtRunRead,
  DashboardLayoutUpdate,
  DashboardRead,
  DashboardSummary,
  DashboardTileCreate,
  DashboardTileRead,
  DashboardUpdate,
  DatasetRead,
  EngineSpec,
  HealthRead,
  InsightRequest,
  InsightResponse,
  LoginRequest,
  MeRead,
  NLChartRequest,
  NLChartResponse,
  NLQueryRequest,
  NLQueryResponse,
  PipelineCreate,
  PipelineRead,
  PipelineUpdate,
  PipelineRunRead,
  PipelineRunSummary,
  QueryRequest,
  QueryResponse,
  SavedChartRead,
  ScheduleCreate,
  ScheduleRead,
  ScheduleUpdate,
  SourceConnectionCreate,
  SourceConnectionRead,
  SourceConnectionUpdate,
  SourceIntrospectResponse,
  SourceTestResponse,
  SemanticModelDefCreate,
  SemanticModelDefRead,
  SemanticModelRead,
  SemanticQueryRequest,
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
// dbt model registry (wizard; mutations require superuser)
// ---------------------------------------------------------------------------

/** GET /dbt-models — the tenant's dbt model definitions. */
export async function listDbtModels(): Promise<DbtModelDefRead[]> {
  return apiFetch<DbtModelDefRead[]>("/dbt-models", {}, { Accept: "application/json" });
}

/** POST /dbt-models — define a dbt model + tests (regenerates the dbt codegen). */
export async function createDbtModel(request: DbtModelDefCreate): Promise<DbtModelDefRead> {
  return apiFetch<DbtModelDefRead>(
    "/dbt-models",
    { method: "POST", body: JSON.stringify(request) },
    { "Content-Type": "application/json" }
  );
}

/** POST /dbt-models/{id}/run — build this model now via Dagster; returns the launched run. */
export async function runDbtModel(id: string): Promise<DbtRunRead> {
  return apiFetch<DbtRunRead>(
    `/dbt-models/${id}/run`,
    { method: "POST" },
    { "Content-Type": "application/json" }
  );
}

/** DELETE /dbt-models/{id}. */
export async function deleteDbtModel(id: string): Promise<void> {
  const response = await fetchWithAuth(`/dbt-models/${id}`, { method: "DELETE" });
  if (!response.ok) {
    throw new Error(`API ${response.status}: ${await parseDetail(response)}`);
  }
}

// ---------------------------------------------------------------------------
// ETL: source connections (mutations require superuser)
// ---------------------------------------------------------------------------

/** GET /sources/kinds — connector kinds the wizard offers. */
export async function listSourceKinds(): Promise<string[]> {
  return apiFetch<string[]>("/sources/kinds", {}, { Accept: "application/json" });
}

/** GET /sources/engines — SQL engines + per-engine defaults for the wizard. */
export async function listSourceEngines(): Promise<EngineSpec[]> {
  return apiFetch<EngineSpec[]>("/sources/engines", {}, { Accept: "application/json" });
}

/** POST /sources/{id}/introspect — drill schema → table → columns for the wizard. */
export async function introspectSource(
  id: string,
  params: { schema?: string; table?: string } = {}
): Promise<SourceIntrospectResponse> {
  const q = new URLSearchParams();
  if (params.schema) q.set("schema", params.schema);
  if (params.table) q.set("table", params.table);
  const qs = q.toString();
  return apiFetch<SourceIntrospectResponse>(
    `/sources/${id}/introspect${qs ? `?${qs}` : ""}`,
    { method: "POST" },
    { "Content-Type": "application/json" }
  );
}

/** GET /sources — the tenant's source connections. */
export async function listSources(): Promise<SourceConnectionRead[]> {
  return apiFetch<SourceConnectionRead[]>("/sources", {}, { Accept: "application/json" });
}

/** POST /sources — create a source connection (secret encrypted at rest). */
export async function createSource(
  request: SourceConnectionCreate
): Promise<SourceConnectionRead> {
  return apiFetch<SourceConnectionRead>(
    "/sources",
    { method: "POST", body: JSON.stringify(request) },
    { "Content-Type": "application/json" }
  );
}

/** PATCH /sources/{id} — partial update (omit `secret` to keep the stored one). */
export async function updateSource(
  id: string,
  request: SourceConnectionUpdate
): Promise<SourceConnectionRead> {
  return apiFetch<SourceConnectionRead>(
    `/sources/${id}`,
    { method: "PATCH", body: JSON.stringify(request) },
    { "Content-Type": "application/json" }
  );
}

/** POST /sources/{id}/test — connectivity check (raises on failure). */
export async function testSource(id: string): Promise<SourceTestResponse> {
  return apiFetch<SourceTestResponse>(
    `/sources/${id}/test`,
    { method: "POST" },
    { "Content-Type": "application/json" }
  );
}

/** DELETE /sources/{id}. */
export async function deleteSource(id: string): Promise<void> {
  const response = await fetchWithAuth(`/sources/${id}`, { method: "DELETE" });
  if (!response.ok) {
    throw new Error(`API ${response.status}: ${await parseDetail(response)}`);
  }
}

// ---------------------------------------------------------------------------
// ETL: pipelines (mutations + run-now require superuser)
// ---------------------------------------------------------------------------

/** GET /pipelines — the tenant's pipelines. */
export async function listPipelines(): Promise<PipelineRead[]> {
  return apiFetch<PipelineRead[]>("/pipelines", {}, { Accept: "application/json" });
}

/** POST /pipelines — create a pipeline. */
export async function createPipeline(request: PipelineCreate): Promise<PipelineRead> {
  return apiFetch<PipelineRead>(
    "/pipelines",
    { method: "POST", body: JSON.stringify(request) },
    { "Content-Type": "application/json" }
  );
}

/** PATCH /pipelines/{id} — partial update (rename, retarget, enable/disable). */
export async function updatePipeline(
  id: string,
  request: PipelineUpdate
): Promise<PipelineRead> {
  return apiFetch<PipelineRead>(
    `/pipelines/${id}`,
    { method: "PATCH", body: JSON.stringify(request) },
    { "Content-Type": "application/json" }
  );
}

/** DELETE /pipelines/{id}. */
export async function deletePipeline(id: string): Promise<void> {
  const response = await fetchWithAuth(`/pipelines/${id}`, { method: "DELETE" });
  if (!response.ok) {
    throw new Error(`API ${response.status}: ${await parseDetail(response)}`);
  }
}

/** POST /pipelines/{id}/run — queue a run now; returns the queued run. */
export async function runPipeline(id: string): Promise<PipelineRunRead> {
  return apiFetch<PipelineRunRead>(
    `/pipelines/${id}/run`,
    { method: "POST" },
    { "Content-Type": "application/json" }
  );
}

/** GET /pipelines/{id}/runs — run history. */
export async function listPipelineRuns(id: string): Promise<PipelineRunRead[]> {
  return apiFetch<PipelineRunRead[]>(`/pipelines/${id}/runs`, {}, { Accept: "application/json" });
}

/** GET /pipelines/runs — recent runs across all the tenant's pipelines (monitoring feed). */
export async function listRecentRuns(limit = 50): Promise<PipelineRunSummary[]> {
  return apiFetch<PipelineRunSummary[]>(
    `/pipelines/runs?limit=${limit}`,
    {},
    { Accept: "application/json" }
  );
}

// ---------------------------------------------------------------------------
// ETL: schedules (mutations require superuser)
// ---------------------------------------------------------------------------

/** GET /schedules — the tenant's schedules. */
export async function listSchedules(): Promise<ScheduleRead[]> {
  return apiFetch<ScheduleRead[]>("/schedules", {}, { Accept: "application/json" });
}

/** POST /schedules — schedule a pipeline on a cron. */
export async function createSchedule(request: ScheduleCreate): Promise<ScheduleRead> {
  return apiFetch<ScheduleRead>(
    "/schedules",
    { method: "POST", body: JSON.stringify(request) },
    { "Content-Type": "application/json" }
  );
}

/** PATCH /schedules/{id} — partial update (e.g. pause/resume via `enabled`). */
export async function updateSchedule(
  id: string,
  request: ScheduleUpdate
): Promise<ScheduleRead> {
  return apiFetch<ScheduleRead>(
    `/schedules/${id}`,
    { method: "PATCH", body: JSON.stringify(request) },
    { "Content-Type": "application/json" }
  );
}

/** DELETE /schedules/{id}. */
export async function deleteSchedule(id: string): Promise<void> {
  const response = await fetchWithAuth(`/schedules/${id}`, { method: "DELETE" });
  if (!response.ok) {
    throw new Error(`API ${response.status}: ${await parseDetail(response)}`);
  }
}

// ---------------------------------------------------------------------------
// Semantic layer (governed models + structured queries)
// ---------------------------------------------------------------------------

/** GET /semantic/models — governed models the tenant may query. */
export async function listSemanticModels(): Promise<SemanticModelRead[]> {
  return apiFetch<SemanticModelRead[]>("/semantic/models", {}, { Accept: "application/json" });
}

/** POST /semantic/query — run a structured, grounded query against the semantic layer. */
export async function querySemantic(
  request: SemanticQueryRequest
): Promise<QueryResponse> {
  return apiFetch<QueryResponse>(
    "/semantic/query",
    { method: "POST", body: JSON.stringify(request) },
    { "Content-Type": "application/json" }
  );
}

// ---------------------------------------------------------------------------
// Semantic-model registry (wizard definitions; mutations need superuser)
// ---------------------------------------------------------------------------

/** GET /semantic-models — the tenant's semantic-model definitions. */
export async function listSemanticModelDefs(): Promise<SemanticModelDefRead[]> {
  return apiFetch<SemanticModelDefRead[]>("/semantic-models", {}, { Accept: "application/json" });
}

/** POST /semantic-models — define a model (regenerates the tenant's Cube codegen). */
export async function createSemanticModelDef(
  request: SemanticModelDefCreate
): Promise<SemanticModelDefRead> {
  return apiFetch<SemanticModelDefRead>(
    "/semantic-models",
    { method: "POST", body: JSON.stringify(request) },
    { "Content-Type": "application/json" }
  );
}

/** DELETE /semantic-models/{id}. */
export async function deleteSemanticModelDef(id: string): Promise<void> {
  const response = await fetchWithAuth(`/semantic-models/${id}`, { method: "DELETE" });
  if (!response.ok) {
    throw new Error(`API ${response.status}: ${await parseDetail(response)}`);
  }
}

// ---------------------------------------------------------------------------
// Saved charts (tenant-scoped CRUD)
// ---------------------------------------------------------------------------

/** GET /charts — the tenant's saved charts, newest first. */
export async function listCharts(): Promise<SavedChartRead[]> {
  return apiFetch<SavedChartRead[]>("/charts", {}, { Accept: "application/json" });
}

/** POST /charts — persist a named ChartSpec. */
export async function createChart(request: ChartCreate): Promise<SavedChartRead> {
  return apiFetch<SavedChartRead>(
    "/charts",
    { method: "POST", body: JSON.stringify(request) },
    { "Content-Type": "application/json" }
  );
}

/** DELETE /charts/{id}. */
export async function deleteChart(id: string): Promise<void> {
  const response = await fetchWithAuth(`/charts/${id}`, { method: "DELETE" });
  if (!response.ok) {
    throw new Error(`API ${response.status}: ${await parseDetail(response)}`);
  }
}

// ---------------------------------------------------------------------------
// Dashboards (tenant-scoped CRUD + tiles + layout)
// ---------------------------------------------------------------------------

/** GET /dashboards — the tenant's dashboards (summaries), newest first. */
export async function listDashboards(): Promise<DashboardSummary[]> {
  return apiFetch<DashboardSummary[]>("/dashboards", {}, { Accept: "application/json" });
}

/** GET /dashboards/{id} — one dashboard with its tiles (each embeds its chart). */
export async function getDashboard(id: string): Promise<DashboardRead> {
  return apiFetch<DashboardRead>(`/dashboards/${id}`, {}, { Accept: "application/json" });
}

/** POST /dashboards — create an empty dashboard. */
export async function createDashboard(request: DashboardCreate): Promise<DashboardRead> {
  return apiFetch<DashboardRead>(
    "/dashboards",
    { method: "POST", body: JSON.stringify(request) },
    { "Content-Type": "application/json" }
  );
}

/** PATCH /dashboards/{id} — rename / re-describe. */
export async function updateDashboard(
  id: string,
  request: DashboardUpdate
): Promise<DashboardRead> {
  return apiFetch<DashboardRead>(
    `/dashboards/${id}`,
    { method: "PATCH", body: JSON.stringify(request) },
    { "Content-Type": "application/json" }
  );
}

/** DELETE /dashboards/{id}. */
export async function deleteDashboard(id: string): Promise<void> {
  const response = await fetchWithAuth(`/dashboards/${id}`, { method: "DELETE" });
  if (!response.ok) {
    throw new Error(`API ${response.status}: ${await parseDetail(response)}`);
  }
}

/** PUT /dashboards/{id}/layout — persist tile order + sizes after a drag/resize. */
export async function setDashboardLayout(
  id: string,
  request: DashboardLayoutUpdate
): Promise<DashboardRead> {
  return apiFetch<DashboardRead>(
    `/dashboards/${id}/layout`,
    { method: "PUT", body: JSON.stringify(request) },
    { "Content-Type": "application/json" }
  );
}

/** POST /dashboards/{id}/tiles — pin a saved chart. */
export async function addDashboardTile(
  dashboardId: string,
  request: DashboardTileCreate
): Promise<DashboardTileRead> {
  return apiFetch<DashboardTileRead>(
    `/dashboards/${dashboardId}/tiles`,
    { method: "POST", body: JSON.stringify(request) },
    { "Content-Type": "application/json" }
  );
}

/** PATCH /dashboards/{id}/tiles/{tileId} — update one tile's title / placement. */
export async function updateDashboardTile(
  dashboardId: string,
  tileId: string,
  request: { title?: string | null; position?: number; w?: number; h?: number }
): Promise<DashboardTileRead> {
  return apiFetch<DashboardTileRead>(
    `/dashboards/${dashboardId}/tiles/${tileId}`,
    { method: "PATCH", body: JSON.stringify(request) },
    { "Content-Type": "application/json" }
  );
}

/** DELETE /dashboards/{id}/tiles/{tileId}. */
export async function deleteDashboardTile(
  dashboardId: string,
  tileId: string
): Promise<void> {
  const response = await fetchWithAuth(
    `/dashboards/${dashboardId}/tiles/${tileId}`,
    { method: "DELETE" }
  );
  if (!response.ok) {
    throw new Error(`API ${response.status}: ${await parseDetail(response)}`);
  }
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

/** POST /ai/chat — grounded tool-calling answer over the semantic layer. */
export async function postChat(request: ChatRequest): Promise<ChatResponse> {
  return apiFetch<ChatResponse>(
    "/ai/chat",
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
