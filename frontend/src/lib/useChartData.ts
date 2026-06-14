/**
 * useChartData — resolve a ChartSpec's data by re-running its grounded query.
 *
 * A saved chart stores only its spec (no data snapshot), so anywhere a chart is
 * displayed (dashboard tiles, previews) we re-run the query the spec describes:
 *  - semantic specs (`query.metric_refs`) → POST /semantic/query
 *  - dataset specs (`query.dataset_id` + `query.query`) → POST /datasets/{id}/query
 *
 * Both underlying query hooks are always called (hook rules), but only the one
 * matching the spec's source is enabled, so exactly one request runs.
 *
 * `filters` lets a caller (e.g. a dashboard filter bar) constrain the re-run at
 * view time. They apply to the **semantic** path only; the server re-validates each
 * filter member against the governed allow-list (see SemanticFilter). Dataset specs
 * carry their own filters inside `spec.query.query`, so they ignore this argument.
 */

import { useDatasetQuery, useSemanticQuery } from "@/api/hooks";
import type {
  ChartSpec,
  QueryRequest,
  SemanticFilter,
  SemanticQueryRequest,
} from "@/types/api";

const EMPTY_QUERY: QueryRequest = { dimensions: [], metrics: [] };
const DEFAULT_LIMIT = 200;

export function useChartData(spec: ChartSpec, filters?: SemanticFilter[]) {
  const metricRefs = spec.query.metric_refs ?? [];
  const isSemantic = metricRefs.length > 0;

  const semanticRequest: SemanticQueryRequest | null = isSemantic
    ? {
        measures: metricRefs,
        dimensions: spec.encoding.x ? [spec.encoding.x] : [],
        limit: DEFAULT_LIMIT,
        ...(filters && filters.length > 0 ? { filters } : {}),
      }
    : null;

  const datasetId =
    !isSemantic && spec.query.dataset_id && spec.query.query ? spec.query.dataset_id : null;
  const datasetRequest = spec.query.query ?? EMPTY_QUERY;

  const semantic = useSemanticQuery(semanticRequest);
  const dataset = useDatasetQuery(datasetId, datasetRequest);

  return isSemantic ? semantic : dataset;
}
