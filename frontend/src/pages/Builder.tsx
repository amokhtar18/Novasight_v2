/**
 * Builder — the low-code chart builder.
 *
 * Two paths to a chart, sharing one renderer + chart-spec:
 *  1. Manual: pick a dataset, a group-by column, a metric, and a chart type;
 *     the structured query runs read-only and renders live.
 *  2. AI: describe the chart in plain English (NLChartPanel).
 *
 * Either result can be pinned to a dashboard.
 */

import { useState } from "react";
import { Link } from "react-router-dom";
import { BarChart3, Database, SlidersHorizontal } from "lucide-react";

import { useDatasets, useDatasetQuery } from "@/api/hooks";
import { PageHeader } from "@/components/layout/PageHeader";
import { ChartRenderer } from "@/components/chart/ChartRenderer";
import { NLChartPanel } from "@/components/chart/NLChartPanel";
import { AddToDashboard } from "@/components/dashboard/AddToDashboard";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Spinner } from "@/components/ui/spinner";
import { EmptyState } from "@/components/ui/empty-state";
import { humanize } from "@/lib/format";
import type {
  AggFunction,
  ChartSpec,
  ChartType,
  NLChartResponse,
  QueryRequest,
} from "@/types/api";

const CHART_TYPES: ChartType[] = ["bar", "line", "area", "pie", "table"];
const AGG_FUNCTIONS: AggFunction[] = ["count", "sum", "avg", "min", "max"];
const METRIC_ALIAS = "value";
const DEFAULT_LIMIT = 50;

export function Builder() {
  const { data: datasets, isLoading: datasetsLoading } = useDatasets();

  const [datasetId, setDatasetId] = useState<string>("");
  const [dimension, setDimension] = useState("");
  const [fn, setFn] = useState<AggFunction>("count");
  const [metricColumn, setMetricColumn] = useState("");
  const [chartType, setChartType] = useState<ChartType>("bar");
  const [aiResult, setAiResult] = useState<NLChartResponse | null>(null);

  // Default the dataset to the first one once loaded.
  const effectiveDatasetId = datasetId || datasets?.[0]?.id || "";

  const dimReady = dimension.trim().length > 0;
  const metricReady = fn === "count" || metricColumn.trim().length > 0;
  const ready = !!effectiveDatasetId && dimReady && metricReady;

  const query: QueryRequest = {
    dimensions: dimReady ? [dimension.trim()] : [],
    metrics: [
      {
        function: fn,
        column: fn === "count" ? undefined : metricColumn.trim() || undefined,
        alias: METRIC_ALIAS,
      },
    ],
    limit: DEFAULT_LIMIT,
  };

  const metricLabel = fn === "count" ? "Count" : `${humanize(fn)} of ${humanize(metricColumn || "")}`;
  const spec: ChartSpec = {
    version: "1",
    type: chartType,
    query: { dataset_id: effectiveDatasetId || null, query },
    encoding: {
      x: dimension.trim() || null,
      series: [{ field: METRIC_ALIAS, name: metricLabel }],
    },
    options: { title: `${metricLabel} by ${humanize(dimension || "")}` },
  };

  const { data, isLoading, isError, error } = useDatasetQuery(
    ready ? effectiveDatasetId : null,
    query
  );

  if (!datasetsLoading && (!datasets || datasets.length === 0)) {
    return (
      <div className="animate-in-up">
        <PageHeader title="Chart builder" />
        <EmptyState
          icon={<Database className="h-6 w-6" />}
          title="No datasets to build from"
          description="Upload a CSV first, then come back to build charts."
          action={
            <Button asChild>
              <Link to="/data">Go to data sources</Link>
            </Button>
          }
        />
      </div>
    );
  }

  return (
    <div className="animate-in-up">
      <PageHeader
        title="Chart builder"
        description="Point-and-click to build a chart, or describe one in plain English. Save the result to a dashboard."
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[320px_1fr]">
        {/* Controls */}
        <Card className="bg-card/70 lg:sticky lg:top-20 lg:self-start">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <SlidersHorizontal className="h-4 w-4" aria-hidden />
              Configure
            </CardTitle>
            <CardDescription>Column names must match your CSV headers.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="b-dataset">Dataset</Label>
              <Select
                id="b-dataset"
                value={effectiveDatasetId}
                onChange={(e) => setDatasetId(e.target.value)}
              >
                {datasets?.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="b-dimension">Group by column</Label>
              <Input
                id="b-dimension"
                value={dimension}
                onChange={(e) => setDimension(e.target.value)}
                placeholder="e.g. category"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="b-fn">Metric</Label>
                <Select id="b-fn" value={fn} onChange={(e) => setFn(e.target.value as AggFunction)}>
                  {AGG_FUNCTIONS.map((f) => (
                    <option key={f} value={f}>
                      {humanize(f)}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="b-metric-col">Column</Label>
                <Input
                  id="b-metric-col"
                  value={metricColumn}
                  onChange={(e) => setMetricColumn(e.target.value)}
                  placeholder={fn === "count" ? "(not needed)" : "e.g. amount"}
                  disabled={fn === "count"}
                />
              </div>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="b-type">Chart type</Label>
              <Select
                id="b-type"
                value={chartType}
                onChange={(e) => setChartType(e.target.value as ChartType)}
              >
                {CHART_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {humanize(t)}
                  </option>
                ))}
              </Select>
            </div>
          </CardContent>
        </Card>

        {/* Preview */}
        <div className="space-y-6">
          <Card className="bg-card/70">
            <CardHeader className="flex-row items-center justify-between space-y-0">
              <CardTitle className="text-base">Preview</CardTitle>
              {ready && data && data.row_count > 0 && (
                <AddToDashboard spec={spec} title={spec.options?.title || "Chart"} />
              )}
            </CardHeader>
            <CardContent>
              {!ready ? (
                <EmptyState
                  icon={<BarChart3 className="h-6 w-6" />}
                  title="Configure your chart"
                  description="Choose a group-by column (and a metric column for sum/avg/min/max) to see a preview."
                />
              ) : isLoading ? (
                <div className="flex h-72 items-center justify-center">
                  <Spinner label="Running query" />
                </div>
              ) : isError ? (
                <Alert variant="destructive">
                  <AlertTitle>Query failed</AlertTitle>
                  <AlertDescription>
                    {error instanceof Error ? error.message : "Check your column names."}
                  </AlertDescription>
                </Alert>
              ) : data && data.row_count > 0 ? (
                <ChartRenderer spec={spec} data={data} title={spec.options?.title ?? undefined} className="h-80" />
              ) : (
                <EmptyState
                  icon={<BarChart3 className="h-6 w-6" />}
                  title="No data to chart"
                  description={`Nothing grouped by "${dimension}". Check the column name matches a CSV header.`}
                />
              )}
            </CardContent>
          </Card>

          {/* AI path */}
          <NLChartPanel onResult={setAiResult} />
          {aiResult && (
            <div className="flex justify-end">
              <AddToDashboard
                spec={aiResult.spec}
                title={aiResult.spec.options?.title ?? "AI chart"}
                data={aiResult.data}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
