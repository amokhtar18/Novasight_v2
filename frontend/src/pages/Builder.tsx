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
import { SemanticQueryBuilder } from "@/components/chart/SemanticQueryBuilder";
import { QueryControls } from "@/components/chart/QueryControls";
import { SavedChartsList } from "@/components/chart/SavedChartsList";
import { AddToDashboard } from "@/components/dashboard/AddToDashboard";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Spinner } from "@/components/ui/spinner";
import { EmptyState } from "@/components/ui/empty-state";
import { humanize } from "@/lib/format";
import { buildSemanticRequest } from "@/lib/useChartData";
import type {
  ChartOptions,
  ChartQuery,
  ChartSort,
  ChartSpec,
  ChartType,
  NLChartResponse,
  NumberFormat,
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

const SORTS: ChartSort[] = ["none", "value_desc", "value_asc", "label_asc", "label_desc"];
const DEFAULT_LIMIT = 50;
// Chart types that present a single value / raw table and so need no category (x) axis.
const NO_X_TYPES: ChartType[] = ["table", "number", "gauge"];

interface FormatState {
  stacked: boolean;
  legend: "top" | "bottom" | "left" | "right" | "hidden";
  dataLabels: boolean;
  sort: ChartSort;
  numberStyle: NumberFormat["style"];
  decimals: string;
  compact: boolean;
  currency: string;
  yMin: string;
  yMax: string;
  logScale: boolean;
}

const DEFAULT_FORMAT: FormatState = {
  stacked: false,
  legend: "top",
  dataLabels: false,
  sort: "none",
  numberStyle: "plain",
  decimals: "",
  compact: false,
  currency: "",
  yMin: "",
  yMax: "",
  logScale: false,
};

/** Compose the display-only ChartOptions for the spec from the format controls. */
function toChartOptions(title: string, f: FormatState): ChartOptions {
  const numOrNull = (s: string): number | null =>
    s.trim() !== "" && Number.isFinite(Number(s)) ? Number(s) : null;
  return {
    title,
    stacked: f.stacked,
    show_legend: f.legend !== "hidden",
    legend_position: f.legend === "hidden" ? "top" : f.legend,
    data_labels: f.dataLabels,
    sort: f.sort,
    log_scale: f.logScale,
    y_min: numOrNull(f.yMin),
    y_max: numOrNull(f.yMax),
    number_format: {
      style: f.numberStyle,
      decimals: f.decimals.trim() !== "" ? Number(f.decimals) : null,
      compact: f.compact,
      currency: f.currency.trim() || null,
    },
  };
}

/** Reverse of `toChartOptions` — restore the format controls from a saved spec. */
function fromChartOptions(o: ChartOptions | undefined): FormatState {
  if (!o) return DEFAULT_FORMAT;
  const nf = o.number_format;
  return {
    stacked: o.stacked ?? false,
    legend: o.show_legend === false ? "hidden" : (o.legend_position ?? "top"),
    dataLabels: o.data_labels ?? false,
    sort: o.sort ?? "none",
    numberStyle: nf?.style ?? "plain",
    decimals: nf?.decimals != null ? String(nf.decimals) : "",
    compact: nf?.compact ?? false,
    currency: nf?.currency ?? "",
    yMin: o.y_min != null ? String(o.y_min) : "",
    yMax: o.y_max != null ? String(o.y_max) : "",
    logScale: o.log_scale ?? false,
  };
}

export function Builder() {
  const semantic = useSemanticBuilder();

  const [aiResult, setAiResult] = useState<NLChartResponse | null>(null);

  return (
    <div className="animate-in-up">
      <PageHeader
        title="Chart builder"
        description="Drag governed dimensions and measures onto the shelves to build a chart — add a breakdown to split it into series — or describe one in plain English. Format it, then save the result."
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[360px_1fr]">
        <Card className="bg-card/70 lg:sticky lg:top-20 lg:self-start">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <SlidersHorizontal className="h-4 w-4" aria-hidden />
              Configure
            </CardTitle>
            <CardDescription>Drag fields onto the shelves, then format the chart.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <SemanticQueryBuilder s={semantic} />
            <QueryControls s={semantic} />
            <FormatControls format={semantic.format} setFormat={semantic.setFormat} />
          </CardContent>
        </Card>

        <div className="space-y-6">
          <SemanticPreview s={semantic} />

          {/* AI path */}
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

          {/* Saved charts — a list (not tiles) you can load back into the builder. */}
          <SavedChartsList onEdit={semantic.loadSpec} />
        </div>
      </div>
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
  const [format, setFormat] = useState<FormatState>(DEFAULT_FORMAT);
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
    version: "1",
    type: chartType,
    query,
    encoding: {
      x: xField,
      series,
      ...(hasBreakdown ? { breakdown } : {}),
    },
    options: toChartOptions(title, format),
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
    setFormat(fromChartOptions(loaded.options));
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
    format,
    setFormat,
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

function FormatControls({
  format: f,
  setFormat,
}: {
  format: FormatState;
  setFormat: (next: FormatState) => void;
}) {
  const set = <K extends keyof FormatState>(key: K, value: FormatState[K]) =>
    setFormat({ ...f, [key]: value });

  return (
    <details className="rounded-lg border bg-background/40 p-3" open={false}>
      <summary className="cursor-pointer text-sm font-medium">Formatting</summary>
      <div className="mt-3 space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="f-legend">Legend</Label>
            <Select
              id="f-legend"
              value={f.legend}
              onChange={(e) => set("legend", e.target.value as FormatState["legend"])}
            >
              {(["top", "bottom", "left", "right", "hidden"] as const).map((p) => (
                <option key={p} value={p}>
                  {humanize(p)}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="f-sort">Sort</Label>
            <Select
              id="f-sort"
              value={f.sort}
              onChange={(e) => set("sort", e.target.value as ChartSort)}
            >
              {SORTS.map((srt) => (
                <option key={srt} value={srt}>
                  {humanize(srt)}
                </option>
              ))}
            </Select>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="f-numstyle">Number format</Label>
            <Select
              id="f-numstyle"
              value={f.numberStyle}
              onChange={(e) => set("numberStyle", e.target.value as NumberFormat["style"])}
            >
              {(["plain", "currency", "percent"] as const).map((st) => (
                <option key={st} value={st}>
                  {humanize(st)}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="f-decimals">Decimals</Label>
            <Input
              id="f-decimals"
              value={f.decimals}
              onChange={(e) => set("decimals", e.target.value)}
              placeholder="auto"
              inputMode="numeric"
            />
          </div>
        </div>

        {f.numberStyle === "currency" && (
          <div className="space-y-1.5">
            <Label htmlFor="f-currency">Currency symbol</Label>
            <Input
              id="f-currency"
              value={f.currency}
              onChange={(e) => set("currency", e.target.value)}
              placeholder="$"
            />
          </div>
        )}

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="f-ymin">Y min</Label>
            <Input
              id="f-ymin"
              value={f.yMin}
              onChange={(e) => set("yMin", e.target.value)}
              placeholder="auto"
              inputMode="numeric"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="f-ymax">Y max</Label>
            <Input
              id="f-ymax"
              value={f.yMax}
              onChange={(e) => set("yMax", e.target.value)}
              placeholder="auto"
              inputMode="numeric"
            />
          </div>
        </div>

        <div className="flex flex-wrap gap-x-4 gap-y-2 text-sm">
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={f.stacked} onChange={(e) => set("stacked", e.target.checked)} />
            Stacked
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={f.dataLabels}
              onChange={(e) => set("dataLabels", e.target.checked)}
            />
            Data labels
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={f.compact} onChange={(e) => set("compact", e.target.checked)} />
            Compact
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={f.logScale}
              onChange={(e) => set("logScale", e.target.checked)}
            />
            Log scale
          </label>
        </div>
      </div>
    </details>
  );
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
