/**
 * Builder — the low-code chart builder (v2, #8).
 *
 * Charts are built on the **governed semantic layer only** (the dataset/CSV path was
 * retired — CSV stays an ingestion on-ramp; model it, then chart it). Two ways to a
 * chart, both emitting the same ChartSpec → one renderer:
 *  1. Point-and-click: pick a model, dimension, measure, chart type, and formatting.
 *  2. AI: describe the chart in plain English (NLChartPanel).
 *
 * The result can be saved server-side (SaveChartButton) or pinned to a dashboard.
 */

import { useEffect, useRef, useState } from "react";
import { BarChart3, Layers, SlidersHorizontal } from "lucide-react";

import { useSemanticModels, useSemanticQuery } from "@/api/hooks";
import { PageHeader } from "@/components/layout/PageHeader";
import { ChartRenderer, type ChartRendererHandle } from "@/components/chart/ChartRenderer";
import { ChartActionsMenu } from "@/components/chart/ChartActionsMenu";
import { NLChartPanel } from "@/components/chart/NLChartPanel";
import { SaveChartButton } from "@/components/chart/SaveChartButton";
import { BuilderDnd, FieldsPalette, Shelves, ChartTypeSelect } from "@/components/chart/SemanticQueryBuilder";
import { QueryControls } from "@/components/chart/QueryControls";
import { AddToDashboard } from "@/components/dashboard/AddToDashboard";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Spinner } from "@/components/ui/spinner";
import { EmptyState } from "@/components/ui/empty-state";
import { buildSemanticRequest } from "@/lib/useChartData";
import { FormatControls } from "@/components/chart/format";
import type {
  ChartOptions,
  ChartQuery,
  ChartSpec,
  ChartType,
  NLChartResponse,
  RelativeDateRange,
  SemanticFilter,
  SemanticGranularity,
} from "@/types/api";

export interface BuilderQueryState {
  measures: string[];
  plainDims: string[];
  timeDimension: { dimension: string; granularity: SemanticGranularity } | null;
  dateRange: RelativeDateRange | string[] | null;
  filters: SemanticFilter[];
  orderBy: { member: string; dir: "asc" | "desc" } | null;
  rowLimit: number;
}

/** Build the spec's ChartQuery from the builder's shelf + query-control state. */
export function buildChartQuery(s: BuilderQueryState): ChartQuery {
  const timeDimensions = s.timeDimension
    ? [
        {
          dimension: s.timeDimension.dimension,
          granularity: s.timeDimension.granularity,
          ...(s.dateRange ? { date_range: s.dateRange } : {}),
        },
      ]
    : [];
  return {
    metric_refs: s.measures,
    dimensions: s.plainDims,
    time_dimensions: timeDimensions,
    filters: s.filters,
    order: s.orderBy ? { [s.orderBy.member]: s.orderBy.dir } : {},
    limit: s.rowLimit,
  };
}

const DEFAULT_LIMIT = 50;
// Chart types that present a single value / raw table and so need no category (x) axis.
const NO_X_TYPES: ChartType[] = ["table", "number", "gauge"];

export function Builder() {
  const semantic = useSemanticBuilder();
  const [aiResult, setAiResult] = useState<NLChartResponse | null>(null);

  return (
    <div className="animate-in-up">
      <PageHeader
        title="Chart builder"
        description="Drag governed fields onto the shelves to build a chart — or describe one in plain English — then format and save it."
      />

      <BuilderDnd s={semantic}>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[220px_1fr_220px]">
          {/* LEFT — Fields */}
          <Card className="bg-card/70 lg:sticky lg:top-20 lg:self-start" elevation="sm">
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-sm">
                <Layers className="h-4 w-4" aria-hidden /> Fields
              </CardTitle>
            </CardHeader>
            <CardContent>
              <FieldsPalette s={semantic} />
            </CardContent>
          </Card>

          {/* CENTER — shelves + preview + AI */}
          <div className="space-y-4">
            <Card className="bg-card/70" elevation="sm">
              <CardContent className="pt-6">
                <Shelves s={semantic} />
              </CardContent>
            </Card>
            <SemanticPreview s={semantic} />
            <NLChartPanel onResult={setAiResult} />
            {aiResult && (
              <div className="flex flex-wrap justify-end gap-2">
                <SaveChartButton spec={aiResult.spec} defaultName={aiResult.spec.options?.title ?? "AI chart"} sourceKind="semantic" />
                <AddToDashboard spec={aiResult.spec} title={aiResult.spec.options?.title ?? "AI chart"} data={aiResult.data} />
              </div>
            )}
          </div>

          {/* RIGHT — type + format + query */}
          <Card className="bg-card/70 lg:sticky lg:top-20 lg:self-start" elevation="sm">
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-sm">
                <SlidersHorizontal className="h-4 w-4" aria-hidden /> Chart
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <ChartTypeSelect s={semantic} />
              <FormatControls options={semantic.options} setOptions={semantic.setOptions} chartType={semantic.chartType} />
              <QueryControls s={semantic} />
            </CardContent>
          </Card>
        </div>
      </BuilderDnd>
    </div>
  );
}

// ===========================================================================
// Semantic-model path
// ===========================================================================

export type SemanticBuilder = ReturnType<typeof useSemanticBuilder>;

export function useSemanticBuilder() {
  const { data: models, isLoading: modelsLoading } = useSemanticModels();

  const [modelName, setModelName] = useState("");
  // The category axis (one dimension), the breakdown dimensions (pivoted into series),
  // and the plotted measures (one or more). Superset-style shelves.
  const [xDim, setXDim] = useState("");
  const [breakdown, setBreakdown] = useState<string[]>([]);
  const [measures, setMeasures] = useState<string[]>([]);
  const [granularity, setGranularity] = useState<SemanticGranularity>("month");
  const [chartType, setChartType] = useState<ChartType>("bar");
  const [options, setOptions] = useState<ChartOptions>({});
  const [rowLimit, setRowLimit] = useState(DEFAULT_LIMIT);
  const [dateRange, setDateRange] = useState<RelativeDateRange | string[] | null>(null);
  const [orderBy, setOrderBy] = useState<{ member: string; dir: "asc" | "desc" } | null>(null);
  const [filters, setFilters] = useState<SemanticFilter[]>([]);

  const model = models?.find((m) => m.name === modelName) ?? models?.[0];

  // Seed sensible defaults (first dimension + first measure) the first time a model is
  // applied, so the builder opens on a working preview. `loadSpec` bumps this ref to the
  // loaded model so loading a saved chart isn't clobbered by re-seeding.
  const seededModel = useRef<string | null>(null);
  useEffect(() => {
    if (!model || seededModel.current === model.name) return;
    seededModel.current = model.name;
    setXDim(model.dimensions[0]?.name ?? "");
    setBreakdown([]);
    setMeasures(model.measures[0] ? [model.measures[0].name] : []);
  }, [model]);

  const addBreakdown = (name: string) =>
    setBreakdown((prev) => (prev.includes(name) || name === xDim ? prev : [...prev, name]));
  const removeBreakdown = (name: string) =>
    setBreakdown((prev) => prev.filter((d) => d !== name));
  const addMeasure = (name: string) =>
    setMeasures((prev) => (prev.includes(name) ? prev : [...prev, name]));
  const removeMeasure = (name: string) => setMeasures((prev) => prev.filter((m) => m !== name));

  // A `time`-typed x dimension is grouped via Cube's timeDimensions with a granularity;
  // the rolled-up column the chart plots is keyed `<dimension>.<granularity>`.
  const isTimeX = model?.dimensions.find((d) => d.name === xDim)?.type === "time";
  const needsX = !NO_X_TYPES.includes(chartType);
  const ready = !!model && measures.length > 0 && (!needsX || !!xDim);

  const xField = xDim ? (isTimeX ? `${xDim}.${granularity}` : xDim) : null;
  // Plain (non-time) dimensions sent to Cube: the category axis (unless it's a time
  // dimension, which goes via time_dimensions) plus every breakdown dimension.
  const plainDims = [...(xDim && !isTimeX ? [xDim] : []), ...breakdown];

  const measureLabel = (name: string) =>
    model?.measures.find((m) => m.name === name)?.title ?? name;
  const dimLabel = (name: string) =>
    model?.dimensions.find((d) => d.name === name)?.title ?? name;

  // With a breakdown the value channel is a single measure (its values are pivoted into
  // one series per breakdown value); otherwise every measure is plotted as a series.
  const hasBreakdown = breakdown.length > 0;
  const series = hasBreakdown
    ? [{ field: measures[0] ?? "", name: measureLabel(measures[0] ?? "") }]
    : measures.map((m) => ({ field: m, name: measureLabel(m) }));

  const title = measures.length
    ? `${measures.map(measureLabel).join(", ")}` +
      (xDim ? ` by ${dimLabel(xDim)}` : "") +
      (isTimeX ? ` (${granularity})` : "") +
      (hasBreakdown ? ` split by ${breakdown.map(dimLabel).join(", ")}` : "")
    : "Chart";

  const query = buildChartQuery({
    measures,
    plainDims,
    timeDimension: isTimeX && xDim ? { dimension: xDim, granularity } : null,
    dateRange,
    filters,
    orderBy,
    rowLimit,
  });

  const spec: ChartSpec = {
    version: "2",
    type: chartType,
    query,
    encoding: {
      x: xField,
      series,
      ...(hasBreakdown ? { breakdown } : {}),
    },
    options: { ...options, title: options.title ?? title },
  };

  const request = ready ? buildSemanticRequest(spec) : null;
  const result = useSemanticQuery(request);

  /** Load a saved (semantic) spec back into the shelves for editing. */
  const loadSpec = (loaded: ChartSpec) => {
    const refs = loaded.query.metric_refs ?? [];
    const td = loaded.query.time_dimensions ?? [];
    const bd = loaded.encoding.breakdown ?? [];
    const dims = loaded.query.dimensions ?? [];
    // x is the time dimension if present, else the plain dimension that isn't a breakdown,
    // else encoding.x (legacy single-dimension specs carried the dimension there only).
    const x = td.length
      ? td[0].dimension
      : (dims.find((d) => !bd.includes(d)) ?? loaded.encoding.x ?? "");
    // Infer the owning model from a field's cube prefix (e.g. "sales.region" → "sales").
    const cube = (refs[0] ?? x ?? bd[0] ?? "").split(".")[0];
    if (cube) {
      seededModel.current = cube;
      setModelName(cube);
    }
    setXDim(x);
    setBreakdown(bd);
    setMeasures(refs);
    if (td[0]?.granularity) setGranularity(td[0].granularity);
    setChartType(loaded.type);
    setOptions(loaded.options ?? {});
    setRowLimit(loaded.query.limit ?? DEFAULT_LIMIT);
    setDateRange(td[0]?.date_range ?? null);
    setFilters(loaded.query.filters ?? []);
    const orderEntry = Object.entries(loaded.query.order ?? {})[0];
    setOrderBy(orderEntry ? { member: orderEntry[0], dir: orderEntry[1] as "asc" | "desc" } : null);
  };

  return {
    models,
    modelsLoading,
    model,
    modelName: model?.name ?? "",
    setModelName,
    xDim,
    setXDim,
    breakdown,
    addBreakdown,
    removeBreakdown,
    measures,
    addMeasure,
    removeMeasure,
    isTimeX: !!isTimeX,
    granularity,
    setGranularity,
    chartType,
    setChartType,
    options,
    setOptions,
    rowLimit,
    setRowLimit,
    dateRange,
    setDateRange,
    orderBy,
    setOrderBy,
    filters,
    setFilters,
    ready,
    spec,
    result,
    loadSpec,
  };
}

function SemanticPreview({ s }: { s: SemanticBuilder }) {
  const { data, isLoading, isError, error } = s.result;
  const hasData = !!data && data.row_count > 0;
  const noModels = !s.modelsLoading && (!s.models || s.models.length === 0);

  const chartHandle = useRef<ChartRendererHandle>(null);

  return (
    <Card className="bg-card/70">
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle className="text-base">Preview</CardTitle>
        {s.ready && hasData && (
          <div className="flex flex-wrap gap-2">
            <ChartActionsMenu spec={s.spec} data={data} chartHandle={chartHandle} title={s.spec.options?.title ?? "Chart"} />
            <SaveChartButton
              spec={s.spec}
              defaultName={s.spec.options?.title ?? "Chart"}
              sourceKind="semantic"
              sourceRef={s.model?.name ?? null}
            />
            <AddToDashboard spec={s.spec} title={s.spec.options?.title || "Chart"} data={data} />
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
            ref={chartHandle}
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
