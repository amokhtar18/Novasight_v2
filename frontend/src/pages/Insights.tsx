/**
 * Insights — generate a plain-language summary of a metric.
 *
 * Pick a dataset + a breakdown, run the aggregation, then ask the AI to
 * summarise the result. The summary is guardrailed server-side (no invented
 * numbers); we render it alongside the supporting chart + table.
 */

import { useState } from "react";
import { Link } from "react-router-dom";
import { Database, Lightbulb, Play } from "lucide-react";

import { useDatasets, useDatasetQuery, useInsight } from "@/api/hooks";
import { PageHeader } from "@/components/layout/PageHeader";
import { ChartRenderer } from "@/components/chart/ChartRenderer";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Spinner } from "@/components/ui/spinner";
import { EmptyState } from "@/components/ui/empty-state";
import { humanize } from "@/lib/format";
import type { AggFunction, ChartSpec, QueryRequest } from "@/types/api";

const AGG_FUNCTIONS: AggFunction[] = ["count", "sum", "avg", "min", "max"];
const METRIC_ALIAS = "value";

export function Insights() {
  const { data: datasets, isLoading: datasetsLoading } = useDatasets();
  const insight = useInsight();

  const [datasetId, setDatasetId] = useState("");
  const [dimension, setDimension] = useState("");
  const [fn, setFn] = useState<AggFunction>("count");
  const [metricColumn, setMetricColumn] = useState("");

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
    limit: 100,
  };

  const metricLabel = fn === "count" ? "Count" : `${humanize(fn)} of ${humanize(metricColumn || "")}`;
  const spec: ChartSpec = {
    version: "1",
    type: "bar",
    query: { dataset_id: effectiveDatasetId || null, query },
    encoding: { x: dimension.trim() || null, series: [{ field: METRIC_ALIAS, name: metricLabel }] },
    options: { title: `${metricLabel} by ${humanize(dimension || "")}` },
  };

  const { data, isLoading, isError } = useDatasetQuery(ready ? effectiveDatasetId : null, query);

  function handleGenerate() {
    if (!data) return;
    insight.mutate({
      columns: data.columns,
      rows: data.rows,
      context_hint: spec.options?.title ?? undefined,
    });
  }

  if (!datasetsLoading && (!datasets || datasets.length === 0)) {
    return (
      <div className="animate-in-up">
        <PageHeader title="Insights" />
        <EmptyState
          icon={<Database className="h-6 w-6" />}
          title="No data to analyse"
          description="Upload a CSV first to generate insights."
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
        title="Insights"
        description="Turn a metric into a short, trustworthy narrative — every number is checked against the data."
      />

      <Card className="mb-6 bg-card/70">
        <CardContent className="grid grid-cols-1 gap-4 pt-6 sm:grid-cols-2 lg:grid-cols-4">
          <div className="space-y-1.5">
            <Label htmlFor="i-dataset">Dataset</Label>
            <Select id="i-dataset" value={effectiveDatasetId} onChange={(e) => setDatasetId(e.target.value)}>
              {datasets?.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="i-dim">Breakdown by</Label>
            <Input id="i-dim" value={dimension} onChange={(e) => setDimension(e.target.value)} placeholder="e.g. region" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="i-fn">Metric</Label>
            <Select id="i-fn" value={fn} onChange={(e) => setFn(e.target.value as AggFunction)}>
              {AGG_FUNCTIONS.map((f) => (
                <option key={f} value={f}>
                  {humanize(f)}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="i-col">Column</Label>
            <Input
              id="i-col"
              value={metricColumn}
              onChange={(e) => setMetricColumn(e.target.value)}
              placeholder={fn === "count" ? "(not needed)" : "e.g. amount"}
              disabled={fn === "count"}
            />
          </div>
        </CardContent>
      </Card>

      {!ready ? (
        <EmptyState
          icon={<Lightbulb className="h-6 w-6" />}
          title="Pick a breakdown to begin"
          description="Choose a dataset and a column to break the metric down by."
        />
      ) : isLoading ? (
        <div className="flex h-40 items-center justify-center">
          <Spinner label="Running query" />
        </div>
      ) : isError || !data ? (
        <Alert variant="destructive">
          <AlertTitle>Query failed</AlertTitle>
          <AlertDescription>Check that the column names match your CSV headers.</AlertDescription>
        </Alert>
      ) : (
        <div className="space-y-6">
          <Card className="bg-card/70">
            <CardHeader className="flex-row items-center justify-between space-y-0">
              <CardTitle className="flex items-center gap-2 text-base">
                <Lightbulb className="h-4 w-4 text-primary" aria-hidden />
                AI summary
              </CardTitle>
              <Button size="sm" onClick={handleGenerate} disabled={insight.isPending || data.row_count === 0}>
                {insight.isPending ? <Spinner className="text-primary-foreground" /> : <Play className="h-4 w-4" aria-hidden />}
                {insight.data ? "Regenerate" : "Generate summary"}
              </Button>
            </CardHeader>
            <CardContent>
              {insight.isError ? (
                <Alert variant="destructive">
                  <AlertTitle>Couldn't summarize</AlertTitle>
                  <AlertDescription>
                    {insight.error instanceof Error ? insight.error.message : "Please try again."}
                  </AlertDescription>
                </Alert>
              ) : insight.data ? (
                <p className="text-sm leading-relaxed">{insight.data.summary}</p>
              ) : (
                <p className="text-sm text-muted-foreground">
                  Run “Generate summary” to get a plain-language readout of this metric.
                </p>
              )}
            </CardContent>
          </Card>

          {data.row_count > 0 && (
            <Card className="bg-card/70">
              <CardHeader>
                <CardTitle className="text-base">{spec.options?.title}</CardTitle>
              </CardHeader>
              <CardContent>
                <ChartRenderer spec={spec} data={data} title={spec.options?.title ?? undefined} className="h-72" />
              </CardContent>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
