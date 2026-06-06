/**
 * Builder — the low-code chart builder.
 *
 * Three ways to a chart, all sharing one renderer + chart-spec:
 *  1. Semantic model: pick a governed model, a dimension, a measure, and a chart
 *     type; the structured query runs read-only against the semantic layer and
 *     renders live. This is the governed, Metabase-/Superset-like path.
 *  2. Dataset: pick a CSV dataset, a group-by column, a metric, and a chart type.
 *  3. AI: describe the chart in plain English (NLChartPanel).
 *
 * Any result can be saved server-side (SaveChartButton) or pinned to a dashboard.
 * State for each path lives in a small hook and is prop-drilled so the controls
 * (left) and the preview (right) share one source of truth.
 */

import { useState } from "react";
import { Link } from "react-router-dom";
import { BarChart3, Database, Layers, SlidersHorizontal } from "lucide-react";

import {
  useDatasets,
  useDatasetQuery,
  useSemanticModels,
  useSemanticQuery,
} from "@/api/hooks";
import { PageHeader } from "@/components/layout/PageHeader";
import { ChartRenderer } from "@/components/chart/ChartRenderer";
import { NLChartPanel } from "@/components/chart/NLChartPanel";
import { SaveChartButton } from "@/components/chart/SaveChartButton";
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
  SemanticQueryRequest,
} from "@/types/api";

const CHART_TYPES: ChartType[] = ["bar", "line", "area", "pie", "table"];
const AGG_FUNCTIONS: AggFunction[] = ["count", "sum", "avg", "min", "max"];
const METRIC_ALIAS = "value";
const DEFAULT_LIMIT = 50;

type SourceMode = "semantic" | "dataset";

export function Builder() {
  const [sourceMode, setSourceMode] = useState<SourceMode>("semantic");
  const [aiResult, setAiResult] = useState<NLChartResponse | null>(null);

  // Both builders are instantiated; each gates its own data query on `active` so
  // the inactive mode never runs a query, but switching modes keeps state.
  const semantic = useSemanticBuilder(sourceMode === "semantic");
  const dataset = useDatasetBuilder(sourceMode === "dataset");

  return (
    <div className="animate-in-up">
      <PageHeader
        title="Chart builder"
        description="Point-and-click to build a chart on a governed model or a dataset, or describe one in plain English. Save the result."
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[320px_1fr]">
        <Card className="bg-card/70 lg:sticky lg:top-20 lg:self-start">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <SlidersHorizontal className="h-4 w-4" aria-hidden />
              Configure
            </CardTitle>
            <CardDescription>Choose a data source, then map it to a chart.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="b-source-mode">Data source</Label>
              <Select
                id="b-source-mode"
                value={sourceMode}
                onChange={(e) => setSourceMode(e.target.value as SourceMode)}
              >
                <option value="semantic">Semantic model</option>
                <option value="dataset">Dataset (CSV)</option>
              </Select>
            </div>

            {sourceMode === "semantic" ? (
              <SemanticControls s={semantic} />
            ) : (
              <DatasetControls d={dataset} />
            )}
          </CardContent>
        </Card>

        <div className="space-y-6">
          {sourceMode === "semantic" ? (
            <SemanticPreview s={semantic} />
          ) : (
            <DatasetPreview d={dataset} />
          )}

          {/* AI path (shared by both modes) */}
          <NLChartPanel onResult={setAiResult} />
          {aiResult && (
            <div className="flex flex-wrap justify-end gap-2">
              <SaveChartButton
                spec={aiResult.spec}
                defaultName={aiResult.spec.options?.title ?? "AI chart"}
                sourceKind="semantic"
              />
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

// ===========================================================================
// Semantic-model path
// ===========================================================================

type SemanticBuilder = ReturnType<typeof useSemanticBuilder>;

function useSemanticBuilder(active: boolean) {
  const { data: models, isLoading: modelsLoading } = useSemanticModels();

  const [modelName, setModelName] = useState("");
  const [dimension, setDimension] = useState("");
  const [measure, setMeasure] = useState("");
  const [chartType, setChartType] = useState<ChartType>("bar");

  const model = models?.find((m) => m.name === modelName) ?? models?.[0];
  const effDimension = dimension || model?.dimensions[0]?.name || "";
  const effMeasure = measure || model?.measures[0]?.name || "";
  const ready = !!model && !!effDimension && !!effMeasure;

  const request: SemanticQueryRequest | null =
    active && ready
      ? { measures: [effMeasure], dimensions: [effDimension], limit: DEFAULT_LIMIT }
      : null;
  const result = useSemanticQuery(request);

  const measureLabel =
    model?.measures.find((m) => m.name === effMeasure)?.title ?? effMeasure;
  const dimLabel =
    model?.dimensions.find((d) => d.name === effDimension)?.title ?? effDimension;

  const spec: ChartSpec = {
    version: "1",
    type: chartType,
    query: { metric_refs: [effMeasure] },
    encoding: {
      x: effDimension || null,
      series: [{ field: effMeasure, name: measureLabel }],
    },
    options: { title: `${measureLabel} by ${dimLabel}` },
  };

  return {
    models,
    modelsLoading,
    model,
    modelName: model?.name ?? "",
    setModelName,
    dimension: effDimension,
    setDimension,
    measure: effMeasure,
    setMeasure,
    chartType,
    setChartType,
    ready,
    spec,
    result,
  };
}

function SemanticControls({ s }: { s: SemanticBuilder }) {
  if (s.modelsLoading) {
    return (
      <div className="flex h-24 items-center justify-center">
        <Spinner label="Loading models" />
      </div>
    );
  }

  if (!s.models || s.models.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No semantic models are available yet. Create one over a data mart, then come
        back to build a chart on it.
      </p>
    );
  }

  return (
    <>
      <div className="space-y-1.5">
        <Label htmlFor="b-model">Model</Label>
        <Select id="b-model" value={s.modelName} onChange={(e) => s.setModelName(e.target.value)}>
          {s.models.map((m) => (
            <option key={m.name} value={m.name}>
              {m.title}
            </option>
          ))}
        </Select>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="b-sem-dim">Dimension</Label>
        <Select id="b-sem-dim" value={s.dimension} onChange={(e) => s.setDimension(e.target.value)}>
          {s.model?.dimensions.map((d) => (
            <option key={d.name} value={d.name}>
              {d.title}
            </option>
          ))}
        </Select>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="b-sem-measure">Measure</Label>
        <Select
          id="b-sem-measure"
          value={s.measure}
          onChange={(e) => s.setMeasure(e.target.value)}
        >
          {s.model?.measures.map((m) => (
            <option key={m.name} value={m.name}>
              {m.title}
            </option>
          ))}
        </Select>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="b-sem-type">Chart type</Label>
        <Select
          id="b-sem-type"
          value={s.chartType}
          onChange={(e) => s.setChartType(e.target.value as ChartType)}
        >
          {CHART_TYPES.map((t) => (
            <option key={t} value={t}>
              {humanize(t)}
            </option>
          ))}
        </Select>
      </div>
    </>
  );
}

function SemanticPreview({ s }: { s: SemanticBuilder }) {
  const { data, isLoading, isError, error } = s.result;
  const hasData = !!data && data.row_count > 0;
  const noModels = !s.modelsLoading && (!s.models || s.models.length === 0);

  return (
    <Card className="bg-card/70">
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle className="text-base">Preview</CardTitle>
        {s.ready && hasData && (
          <div className="flex flex-wrap gap-2">
            <SaveChartButton
              spec={s.spec}
              defaultName={s.spec.options?.title ?? "Chart"}
              sourceKind="semantic"
              sourceRef={s.model?.name ?? null}
            />
            <AddToDashboard
              spec={s.spec}
              title={s.spec.options?.title || "Chart"}
              data={data}
            />
          </div>
        )}
      </CardHeader>
      <CardContent>
        {noModels ? (
          <EmptyState
            icon={<Layers className="h-6 w-6" />}
            title="No semantic models"
            description="Build a semantic model over a data mart first, then chart it here."
          />
        ) : !s.ready ? (
          <EmptyState
            icon={<BarChart3 className="h-6 w-6" />}
            title="Configure your chart"
            description="Pick a model, a dimension, and a measure to see a live preview."
          />
        ) : isLoading ? (
          <div className="flex h-72 items-center justify-center">
            <Spinner label="Running query" />
          </div>
        ) : isError ? (
          <Alert variant="destructive">
            <AlertTitle>Query failed</AlertTitle>
            <AlertDescription>
              {error instanceof Error ? error.message : "The semantic query could not run."}
            </AlertDescription>
          </Alert>
        ) : hasData ? (
          <ChartRenderer
            spec={s.spec}
            data={data}
            title={s.spec.options?.title ?? undefined}
            className="h-80"
          />
        ) : (
          <EmptyState
            icon={<BarChart3 className="h-6 w-6" />}
            title="No data to chart"
            description="This model returned no rows for the chosen dimension and measure."
          />
        )}
      </CardContent>
    </Card>
  );
}

// ===========================================================================
// Dataset path
// ===========================================================================

type DatasetBuilder = ReturnType<typeof useDatasetBuilder>;

function useDatasetBuilder(active: boolean) {
  const { data: datasets, isLoading: datasetsLoading } = useDatasets();

  const [datasetId, setDatasetId] = useState<string>("");
  const [dimension, setDimension] = useState("");
  const [fn, setFn] = useState<AggFunction>("count");
  const [metricColumn, setMetricColumn] = useState("");
  const [chartType, setChartType] = useState<ChartType>("bar");

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
  const result = useDatasetQuery(active && ready ? effectiveDatasetId : null, query);

  const metricLabel =
    fn === "count" ? "Count" : `${humanize(fn)} of ${humanize(metricColumn || "")}`;
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

  return {
    datasets,
    datasetsLoading,
    datasetId: effectiveDatasetId,
    setDatasetId,
    dimension,
    setDimension,
    fn,
    setFn,
    metricColumn,
    setMetricColumn,
    chartType,
    setChartType,
    ready,
    spec,
    result,
  };
}

function DatasetControls({ d }: { d: DatasetBuilder }) {
  if (!d.datasetsLoading && (!d.datasets || d.datasets.length === 0)) {
    return (
      <p className="text-sm text-muted-foreground">
        No datasets yet.{" "}
        <Link to="/data" className="underline">
          Upload a CSV
        </Link>{" "}
        to build a chart on it.
      </p>
    );
  }

  return (
    <>
      <div className="space-y-1.5">
        <Label htmlFor="b-dataset">Dataset</Label>
        <Select id="b-dataset" value={d.datasetId} onChange={(e) => d.setDatasetId(e.target.value)}>
          {d.datasets?.map((ds) => (
            <option key={ds.id} value={ds.id}>
              {ds.name}
            </option>
          ))}
        </Select>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="b-dimension">Group by column</Label>
        <Input
          id="b-dimension"
          value={d.dimension}
          onChange={(e) => d.setDimension(e.target.value)}
          placeholder="e.g. category"
        />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1.5">
          <Label htmlFor="b-fn">Metric</Label>
          <Select id="b-fn" value={d.fn} onChange={(e) => d.setFn(e.target.value as AggFunction)}>
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
            value={d.metricColumn}
            onChange={(e) => d.setMetricColumn(e.target.value)}
            placeholder={d.fn === "count" ? "(not needed)" : "e.g. amount"}
            disabled={d.fn === "count"}
          />
        </div>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="b-type">Chart type</Label>
        <Select
          id="b-type"
          value={d.chartType}
          onChange={(e) => d.setChartType(e.target.value as ChartType)}
        >
          {CHART_TYPES.map((t) => (
            <option key={t} value={t}>
              {humanize(t)}
            </option>
          ))}
        </Select>
      </div>
    </>
  );
}

function DatasetPreview({ d }: { d: DatasetBuilder }) {
  const { data, isLoading, isError, error } = d.result;
  const hasData = !!data && data.row_count > 0;
  const noDatasets = !d.datasetsLoading && (!d.datasets || d.datasets.length === 0);

  return (
    <Card className="bg-card/70">
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle className="text-base">Preview</CardTitle>
        {d.ready && hasData && (
          <div className="flex flex-wrap gap-2">
            <SaveChartButton
              spec={d.spec}
              defaultName={d.spec.options?.title ?? "Chart"}
              sourceKind="dataset"
              sourceRef={d.datasetId || null}
            />
            <AddToDashboard spec={d.spec} title={d.spec.options?.title || "Chart"} />
          </div>
        )}
      </CardHeader>
      <CardContent>
        {noDatasets ? (
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
        ) : !d.ready ? (
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
        ) : hasData ? (
          <ChartRenderer
            spec={d.spec}
            data={data}
            title={d.spec.options?.title ?? undefined}
            className="h-80"
          />
        ) : (
          <EmptyState
            icon={<BarChart3 className="h-6 w-6" />}
            title="No data to chart"
            description={`Nothing grouped by "${d.dimension}". Check the column name matches a CSV header.`}
          />
        )}
      </CardContent>
    </Card>
  );
}
