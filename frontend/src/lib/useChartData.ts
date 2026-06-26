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
  RelativeDateRange,
  SemanticFilter,
  SemanticQueryRequest,
} from "@/types/api";

const EMPTY_QUERY: QueryRequest = { dimensions: [], metrics: [] };
const DEFAULT_LIMIT = 200;

/**
 * Build the SemanticQueryRequest a ChartSpec describes. Forwards spec-level
 * order/limit/filters and merges any view-time filters (spec filters first).
 * Returns null for a non-semantic (dataset) spec.
 */
export function buildSemanticRequest(
  spec: ChartSpec | null,
  viewFilters?: SemanticFilter[],
  dateRangeOverrides?: Record<string, RelativeDateRange | string[]>
): SemanticQueryRequest | null {
  const metricRefs = spec?.query.metric_refs ?? [];
  if (!spec || metricRefs.length === 0) return null;

  const rawTimeDimensions = spec.query.time_dimensions ?? [];
  // Apply any view-time date_range override to the matching time dimension (by member).
  const timeDimensions = rawTimeDimensions.map((td) =>
    dateRangeOverrides && dateRangeOverrides[td.dimension] !== undefined
      ? { ...td, date_range: dateRangeOverrides[td.dimension] }
      : td
  );
  const hasTimeDim = timeDimensions.length > 0;
  const plainDimensions =
    spec.query.dimensions && spec.query.dimensions.length > 0
      ? spec.query.dimensions
      : hasTimeDim || !spec.encoding.x
        ? []
        : [spec.encoding.x];

  const specFilters = spec.query.filters ?? [];
  const filters = [...specFilters, ...(viewFilters ?? [])];

  return {
    measures: metricRefs,
    dimensions: plainDimensions,
    ...(hasTimeDim ? { time_dimensions: timeDimensions } : {}),
    ...(spec.query.order && Object.keys(spec.query.order).length > 0
      ? { order: spec.query.order }
      : {}),
    limit: spec.query.limit ?? DEFAULT_LIMIT,
    ...(filters.length > 0 ? { filters } : {}),
  };
}

export function useChartData(
  spec: ChartSpec | null,
  filters?: SemanticFilter[],
  dateRangeOverrides?: Record<string, RelativeDateRange | string[]>
) {
  const isSemantic = (spec?.query.metric_refs ?? []).length > 0;

  const semanticRequest = buildSemanticRequest(spec, filters, dateRangeOverrides);

  const datasetId =
    !isSemantic && spec?.query.dataset_id && spec.query.query ? spec.query.dataset_id : null;
  const datasetRequest = spec?.query.query ?? EMPTY_QUERY;

  const semantic = useSemanticQuery(semanticRequest);
  const dataset = useDatasetQuery(datasetId, datasetRequest);

  return isSemantic ? semantic : dataset;
}
