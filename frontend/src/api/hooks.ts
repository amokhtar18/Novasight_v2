/**
 * TanStack Query hooks for the NovaSight API.
 *
 * All server state goes through these hooks.
 * Components import from here, never directly from the API client.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import {
  addDashboardTile,
  createChart,
  createDashboard,
  createDbtModel,
  createPipeline,
  createSchedule,
  createSemanticModelDef,
  createSource,
  createUser,
  deleteChart,
  deleteDashboard,
  deleteDashboardTile,
  deleteDbtModel,
  deletePipeline,
  deleteSchedule,
  deleteSemanticModelDef,
  deleteSource,
  deleteUser,
  deprovisionTenant,
  getDashboard,
  getHealth,
  getMe,
  getSuggestions,
  introspectSource,
  listCharts,
  listDashboards,
  listDatasets,
  listDbtModels,
  listPipelineRuns,
  listPipelines,
  listRecentRuns,
  listSchedules,
  listSemanticModelDefs,
  listSemanticModels,
  listSourceEngines,
  listSourceKinds,
  listSources,
  listTenants,
  listUsers,
  login,
  logout,
  postChat,
  postInsight,
  postNLChart,
  postNLQuery,
  provisionTenant,
  queryDataset,
  querySemantic,
  runDbtModel,
  runPipeline,
  setDashboardLayout,
  testSource,
  updateDashboard,
  updateDashboardTile,
  updateDbtModel,
  updatePipeline,
  updateSchedule,
  updateSemanticModelDef,
  updateSource,
  updateUser,
  uploadDataset,
} from "./client";
import { useAuthStore } from "@/store/authStore";
import type {
  ChartCreate,
  ChatRequest,
  DashboardCreate,
  DashboardLayoutUpdate,
  DashboardTileCreate,
  DashboardUpdate,
  DbtModelDefCreate,
  DbtModelDefUpdate,
  InsightRequest,
  LoginRequest,
  NLChartRequest,
  NLQueryRequest,
  PipelineCreate,
  PipelineUpdate,
  QueryRequest,
  ScheduleCreate,
  ScheduleUpdate,
  SemanticModelDefCreate,
  SemanticModelDefUpdate,
  SemanticQueryRequest,
  SourceConnectionCreate,
  SourceConnectionUpdate,
  TenantProvisionRequest,
  UserCreate,
  UserUpdate,
} from "@/types/api";

// Query-key factory — keeps keys consistent and refactorable.
export const queryKeys = {
  me: () => ["me"] as const,
  health: () => ["health"] as const,
  datasets: () => ["datasets"] as const,
  datasetQuery: (id: string, req: QueryRequest) =>
    ["datasets", id, "query", req] as const,
  suggestions: (id: string) => ["datasets", id, "suggestions"] as const,
  semanticModels: () => ["semantic", "models"] as const,
  semanticModelDefs: () => ["semantic-models"] as const,
  sources: () => ["sources"] as const,
  pipelines: () => ["pipelines"] as const,
  pipelineRuns: (id: string) => ["pipelines", id, "runs"] as const,
  recentRuns: () => ["pipelines", "runs", "recent"] as const,
  schedules: () => ["schedules"] as const,
  dbtModels: () => ["dbt-models"] as const,
  semanticQuery: (req: SemanticQueryRequest) => ["semantic", "query", req] as const,
  charts: () => ["charts"] as const,
  dashboards: () => ["dashboards"] as const,
  dashboard: (id: string) => ["dashboards", id] as const,
  users: () => ["users"] as const,
  tenants: () => ["tenants"] as const,
};

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

/** Mutation: log in. On success, records the session in the auth store. */
export function useLogin() {
  return useMutation({
    mutationFn: (request: LoginRequest) => login(request),
    onSuccess: (data) => {
      useAuthStore.getState().setSession({
        accessToken: data.access_token,
        refreshToken: data.refresh_token,
        user: data.user,
      });
    },
  });
}

/** Mutation: log out. Clears the session + cached server state. */
export function useLogout() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => logout(),
    onSettled: () => {
      useAuthStore.getState().clear();
      client.clear();
    },
  });
}

/** Query: resolved tenant context for the authenticated caller. */
export function useMe() {
  return useQuery({
    queryKey: queryKeys.me(),
    queryFn: getMe,
    staleTime: 5 * 60_000,
  });
}

/** Query: component health. Polls so the Overview/Admin badges stay fresh. */
export function useHealth() {
  return useQuery({
    queryKey: queryKeys.health(),
    queryFn: getHealth,
    refetchInterval: 30_000,
    staleTime: 15_000,
  });
}

/** Mutation: upload a CSV file. Invalidates the datasets list on success. */
export function useUploadDataset() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => uploadDataset(file),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.datasets() });
    },
  });
}

/** Query: list all tenant datasets. */
export function useDatasets() {
  return useQuery({
    queryKey: queryKeys.datasets(),
    queryFn: listDatasets,
  });
}

/**
 * Query: run a structured aggregation against a dataset.
 * Only enabled when `datasetId` is provided.
 */
export function useDatasetQuery(datasetId: string | null, request: QueryRequest) {
  return useQuery({
    queryKey:
      datasetId !== null
        ? queryKeys.datasetQuery(datasetId, request)
        : (["noop"] as const),
    queryFn: () => {
      if (!datasetId) throw new Error("datasetId is required");
      return queryDataset(datasetId, request);
    },
    enabled: datasetId !== null,
    staleTime: 30_000,
  });
}

/**
 * Mutation: submit a natural-language chart description to POST /api/v1/ai/chart.
 *
 * This is a mutation (not a query) because it is user-triggered and not
 * idempotent in the general case — the LLM may return a different spec on each
 * call. Callers distinguish error kinds via `NLChartError.kind`:
 *   - `"ungroundable"` → 422 → show fallback to manual builder
 *   - `"service_unavailable"` → 503 → show retry message
 */
export function useNLChart() {
  return useMutation({
    mutationFn: (request: NLChartRequest) => postNLChart(request),
  });
}

/** Mutation: chat — grounded tool-calling answer over the semantic layer. */
export function useChat() {
  return useMutation({
    mutationFn: (request: ChatRequest) => postChat(request),
  });
}

/** Mutation: NL→SQL — translate a question to validated SQL and execute it. */
export function useNLQuery() {
  return useMutation({
    mutationFn: (request: NLQueryRequest) => postNLQuery(request),
  });
}

/** Mutation: generate a validated insight summary from a result set. */
export function useInsight() {
  return useMutation({
    mutationFn: (request: InsightRequest) => postInsight(request),
  });
}

/**
 * Query: AI chart suggestions for a dataset. Disabled until `enabled` is true
 * so profiling (an LLM call) only runs when the user opens the detail view.
 */
export function useSuggestions(datasetId: string | null, enabled = true) {
  return useQuery({
    queryKey:
      datasetId !== null ? queryKeys.suggestions(datasetId) : (["noop"] as const),
    queryFn: () => {
      if (!datasetId) throw new Error("datasetId is required");
      return getSuggestions(datasetId);
    },
    enabled: datasetId !== null && enabled,
    staleTime: 5 * 60_000,
    retry: 0,
  });
}

// ---------------------------------------------------------------------------
// Semantic layer
// ---------------------------------------------------------------------------

/** Query: governed semantic models the tenant may build charts on. */
export function useSemanticModels() {
  return useQuery({
    queryKey: queryKeys.semanticModels(),
    queryFn: listSemanticModels,
    staleTime: 5 * 60_000,
    retry: 0,
  });
}

/**
 * Query: run a structured, grounded query against the semantic layer.
 * Only enabled when a request is provided (the builder gates this until the
 * user has picked a dimension + measure).
 */
export function useSemanticQuery(request: SemanticQueryRequest | null) {
  return useQuery({
    queryKey:
      request !== null ? queryKeys.semanticQuery(request) : (["noop"] as const),
    queryFn: () => {
      if (!request) throw new Error("a semantic query request is required");
      return querySemantic(request);
    },
    enabled: request !== null,
    staleTime: 30_000,
    retry: 0,
  });
}

// ---------------------------------------------------------------------------
// Semantic-model registry (wizard definitions)
// ---------------------------------------------------------------------------

/** Query: the tenant's semantic-model definitions. */
export function useSemanticModelDefs() {
  return useQuery({
    queryKey: queryKeys.semanticModelDefs(),
    queryFn: listSemanticModelDefs,
  });
}

/** Mutation: define a semantic model. Invalidates defs + governed models. */
export function useCreateSemanticModelDef() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (request: SemanticModelDefCreate) => createSemanticModelDef(request),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.semanticModelDefs() });
      void client.invalidateQueries({ queryKey: queryKeys.semanticModels() });
    },
  });
}

/** Mutation: update a semantic-model definition. Invalidates defs + governed models. */
export function useUpdateSemanticModelDef() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: SemanticModelDefUpdate }) =>
      updateSemanticModelDef(id, patch),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.semanticModelDefs() });
      void client.invalidateQueries({ queryKey: queryKeys.semanticModels() });
    },
  });
}

/** Mutation: delete a semantic-model definition. Invalidates defs + governed models. */
export function useDeleteSemanticModelDef() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteSemanticModelDef(id),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.semanticModelDefs() });
      void client.invalidateQueries({ queryKey: queryKeys.semanticModels() });
    },
  });
}

// ---------------------------------------------------------------------------
// ETL: source connections
// ---------------------------------------------------------------------------

/** Query: connector kinds the wizard offers. */
export function useSourceKinds() {
  return useQuery({
    queryKey: ["sources", "kinds"] as const,
    queryFn: listSourceKinds,
    staleTime: 60 * 60_000,
  });
}

/** Query: SQL engines + per-engine defaults for the connection wizard. */
export function useSourceEngines() {
  return useQuery({
    queryKey: ["sources", "engines"] as const,
    queryFn: listSourceEngines,
    staleTime: 60 * 60_000,
  });
}

/** Mutation: drill schema → table → columns on a source for the pipeline wizard. */
export function useIntrospectSource() {
  return useMutation({
    mutationFn: (vars: { id: string; schema?: string; table?: string }) =>
      introspectSource(vars.id, { schema: vars.schema, table: vars.table }),
  });
}

/** Query: the tenant's source connections. */
export function useSources() {
  return useQuery({ queryKey: queryKeys.sources(), queryFn: listSources });
}

/** Mutation: create a source connection. Invalidates the sources list. */
export function useCreateSource() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (request: SourceConnectionCreate) => createSource(request),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.sources() });
    },
  });
}

/** Mutation: update a source connection (partial). Invalidates the sources list. */
export function useUpdateSource() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: SourceConnectionUpdate }) =>
      updateSource(id, patch),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.sources() });
    },
  });
}

/** Mutation: test a source connection's connectivity. */
export function useTestSource() {
  return useMutation({ mutationFn: (id: string) => testSource(id) });
}

/** Mutation: delete a source connection. Invalidates the sources list. */
export function useDeleteSource() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteSource(id),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.sources() });
    },
  });
}

// ---------------------------------------------------------------------------
// ETL: pipelines
// ---------------------------------------------------------------------------

/** Query: the tenant's pipelines. */
export function usePipelines() {
  return useQuery({ queryKey: queryKeys.pipelines(), queryFn: listPipelines });
}

/** Query: a pipeline's run history. Disabled until an id is provided. */
export function usePipelineRuns(id: string | null) {
  return useQuery({
    queryKey: id !== null ? queryKeys.pipelineRuns(id) : (["noop"] as const),
    queryFn: () => {
      if (!id) throw new Error("pipeline id is required");
      return listPipelineRuns(id);
    },
    enabled: id !== null,
  });
}

/**
 * Query: recent runs across all the tenant's pipelines (the Operations monitor).
 * Polls so the feed stays live while a run progresses.
 */
export function useRecentRuns(limit = 50) {
  return useQuery({
    queryKey: queryKeys.recentRuns(),
    queryFn: () => listRecentRuns(limit),
    refetchInterval: 10_000,
    staleTime: 5_000,
  });
}

/** Mutation: create a pipeline. Invalidates the pipelines list. */
export function useCreatePipeline() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (request: PipelineCreate) => createPipeline(request),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.pipelines() });
    },
  });
}

/** Mutation: update a pipeline (partial). Invalidates the pipelines list. */
export function useUpdatePipeline() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: PipelineUpdate }) =>
      updatePipeline(id, patch),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.pipelines() });
    },
  });
}

/** Mutation: delete a pipeline. Invalidates the pipelines list. */
export function useDeletePipeline() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deletePipeline(id),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.pipelines() });
    },
  });
}

/** Mutation: run a pipeline now. Invalidates that pipeline's run history. */
export function useRunPipeline() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => runPipeline(id),
    onSuccess: (_run, id) => {
      void client.invalidateQueries({ queryKey: queryKeys.pipelineRuns(id) });
    },
  });
}

// ---------------------------------------------------------------------------
// ETL: schedules
// ---------------------------------------------------------------------------

/** Query: the tenant's schedules. */
export function useSchedules() {
  return useQuery({ queryKey: queryKeys.schedules(), queryFn: listSchedules });
}

/** Mutation: schedule a pipeline. Invalidates the schedules list. */
export function useCreateSchedule() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (request: ScheduleCreate) => createSchedule(request),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.schedules() });
    },
  });
}

/** Mutation: update a schedule (e.g. pause/resume). Invalidates the schedules list. */
export function useUpdateSchedule() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: ScheduleUpdate }) =>
      updateSchedule(id, patch),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.schedules() });
    },
  });
}

/** Mutation: delete a schedule. Invalidates the schedules list. */
export function useDeleteSchedule() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteSchedule(id),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.schedules() });
    },
  });
}

// ---------------------------------------------------------------------------
// dbt model registry (wizard)
// ---------------------------------------------------------------------------

/** Query: the tenant's dbt model definitions. */
export function useDbtModels() {
  return useQuery({ queryKey: queryKeys.dbtModels(), queryFn: listDbtModels });
}

/** Mutation: define a dbt model. Invalidates the list. */
export function useCreateDbtModel() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (request: DbtModelDefCreate) => createDbtModel(request),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.dbtModels() });
    },
  });
}

/** Mutation: update a dbt model (partial). Invalidates the list. */
export function useUpdateDbtModel() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: DbtModelDefUpdate }) =>
      updateDbtModel(id, patch),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.dbtModels() });
    },
  });
}

/** Mutation: delete a dbt model. Invalidates the list. */
export function useDeleteDbtModel() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteDbtModel(id),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.dbtModels() });
    },
  });
}

/** Mutation: build a dbt model now via Dagster. No list change — returns the launched run. */
export function useRunDbtModel() {
  return useMutation({
    mutationFn: (id: string) => runDbtModel(id),
  });
}

// ---------------------------------------------------------------------------
// Saved charts
// ---------------------------------------------------------------------------

/** Query: the tenant's saved charts. */
export function useCharts(enabled = true) {
  return useQuery({
    queryKey: queryKeys.charts(),
    queryFn: listCharts,
    enabled,
  });
}

/** Mutation: save a chart. Invalidates the charts list on success. */
export function useCreateChart() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (request: ChartCreate) => createChart(request),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.charts() });
    },
  });
}

/** Mutation: delete a saved chart. Invalidates the charts list. */
export function useDeleteChart() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteChart(id),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.charts() });
    },
  });
}

// ---------------------------------------------------------------------------
// Dashboards
// ---------------------------------------------------------------------------

/** Query: the tenant's dashboards (summaries). */
export function useDashboards() {
  return useQuery({
    queryKey: queryKeys.dashboards(),
    queryFn: listDashboards,
  });
}

/** Query: one dashboard with its tiles. Disabled until an id is provided. */
export function useDashboard(id: string | null) {
  return useQuery({
    queryKey: id !== null ? queryKeys.dashboard(id) : (["noop"] as const),
    queryFn: () => {
      if (!id) throw new Error("dashboard id is required");
      return getDashboard(id);
    },
    enabled: id !== null,
  });
}

/** Mutation: create a dashboard. Invalidates the list. */
export function useCreateDashboard() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (request: DashboardCreate) => createDashboard(request),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.dashboards() });
    },
  });
}

/** Mutation: rename / re-describe a dashboard. Invalidates list + detail. */
export function useUpdateDashboard() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: DashboardUpdate }) =>
      updateDashboard(id, patch),
    onSuccess: (data) => {
      void client.invalidateQueries({ queryKey: queryKeys.dashboards() });
      void client.invalidateQueries({ queryKey: queryKeys.dashboard(data.id) });
    },
  });
}

/** Mutation: delete a dashboard. Invalidates the list. */
export function useDeleteDashboard() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteDashboard(id),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.dashboards() });
    },
  });
}

/** Mutation: pin a saved chart onto a dashboard. Invalidates that dashboard. */
export function useAddDashboardTile() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ dashboardId, tile }: { dashboardId: string; tile: DashboardTileCreate }) =>
      addDashboardTile(dashboardId, tile),
    onSuccess: (_data, vars) => {
      void client.invalidateQueries({ queryKey: queryKeys.dashboard(vars.dashboardId) });
      void client.invalidateQueries({ queryKey: queryKeys.dashboards() });
    },
  });
}

/** Mutation: update one tile (e.g. resize). Invalidates that dashboard. */
export function useUpdateDashboardTile(dashboardId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      tileId,
      patch,
    }: {
      tileId: string;
      patch: { title?: string | null; position?: number; w?: number; h?: number };
    }) => updateDashboardTile(dashboardId, tileId, patch),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.dashboard(dashboardId) });
    },
  });
}

/** Mutation: remove a tile. Invalidates that dashboard + the list (tile counts). */
export function useDeleteDashboardTile(dashboardId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (tileId: string) => deleteDashboardTile(dashboardId, tileId),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.dashboard(dashboardId) });
      void client.invalidateQueries({ queryKey: queryKeys.dashboards() });
    },
  });
}

/** Mutation: persist the whole grid (drag-reorder + resize). */
export function useSetDashboardLayout(dashboardId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (layout: DashboardLayoutUpdate) => setDashboardLayout(dashboardId, layout),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.dashboard(dashboardId) });
    },
  });
}

/** Mutation: provision a new tenant (platform admin). */
export function useProvisionTenant() {
  return useMutation({
    mutationFn: (request: TenantProvisionRequest) => provisionTenant(request),
  });
}

/** Mutation: de-provision a tenant by slug (platform admin). */
export function useDeprovisionTenant() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (slug: string) => deprovisionTenant(slug),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.tenants() });
    },
  });
}

/** Query: list all tenants (platform admin). */
export function useTenants(enabled = true) {
  return useQuery({
    queryKey: queryKeys.tenants(),
    queryFn: listTenants,
    enabled,
    retry: 0,
  });
}

// ---------------------------------------------------------------------------
// User management (tenant superuser)
// ---------------------------------------------------------------------------

/** Query: list the tenant's users. */
export function useUsers(enabled = true) {
  return useQuery({
    queryKey: queryKeys.users(),
    queryFn: listUsers,
    enabled,
    retry: 0,
  });
}

/** Mutation: create a user. Invalidates the users list. */
export function useCreateUser() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (request: UserCreate) => createUser(request),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.users() });
    },
  });
}

/** Mutation: update a user. Invalidates the users list. */
export function useUpdateUser() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: UserUpdate }) =>
      updateUser(id, patch),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.users() });
    },
  });
}

/** Mutation: delete a user. Invalidates the users list. */
export function useDeleteUser() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteUser(id),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.users() });
    },
  });
}
