/**
 * SpecChart — render a re-runnable ChartSpec (inline dataset path) by fetching
 * its data via the dataset query endpoint. For specs that carry their own data,
 * use ChartRenderer directly instead.
 */

import { ChartRenderer } from "@/components/chart/ChartRenderer";
import { Spinner } from "@/components/ui/spinner";
import { EmptyState } from "@/components/ui/empty-state";
import { useDatasetQuery } from "@/api/hooks";
import type { ChartSpec, QueryRequest } from "@/types/api";

const EMPTY_QUERY: QueryRequest = { dimensions: [], metrics: [] };

export function SpecChart({
  spec,
  title,
  className = "h-64",
}: {
  spec: ChartSpec;
  title?: string;
  className?: string;
}) {
  const datasetId = spec.query.dataset_id ?? null;
  const request = spec.query.query ?? EMPTY_QUERY;
  const { data, isLoading, isError } = useDatasetQuery(datasetId, request);

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Spinner label="Loading chart" />
      </div>
    );
  }
  if (isError || !data) {
    return <EmptyState title="Couldn't load data" description="The query failed to run." />;
  }
  if (data.row_count === 0) {
    return <EmptyState title="No data" description="This chart returned no rows." />;
  }
  return <ChartRenderer spec={spec} data={data} title={title} className={className} />;
}
