/**
 * TanStack Query hooks for the Analytica API.
 *
 * All server state goes through these hooks.
 * Components import from here, never directly from the API client.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { listDatasets, postNLChart, queryDataset, uploadDataset } from "./client";
import type { NLChartRequest, QueryRequest } from "@/types/api";

// Query-key factory — keeps keys consistent and refactorable.
export const queryKeys = {
  datasets: () => ["datasets"] as const,
  datasetQuery: (id: string, req: QueryRequest) =>
    ["datasets", id, "query", req] as const,
};

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
