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
  createUser,
  deleteUser,
  deprovisionTenant,
  getHealth,
  getMe,
  getSuggestions,
  listDatasets,
  listTenants,
  listUsers,
  login,
  logout,
  postInsight,
  postNLChart,
  postNLQuery,
  provisionTenant,
  queryDataset,
  updateUser,
  uploadDataset,
} from "./client";
import { useAuthStore } from "@/store/authStore";
import type {
  InsightRequest,
  LoginRequest,
  NLChartRequest,
  NLQueryRequest,
  QueryRequest,
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
