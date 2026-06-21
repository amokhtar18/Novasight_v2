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

import { useState } from "react";
import { BarChart3, Layers, SlidersHorizontal } from "lucide-react";

import { useSemanticModels, useSemanticQuery } from "@/api/hooks";
import { PageHeader } from "@/components/layout/PageHeader";
import { ChartRenderer } from "@/components/chart/ChartRenderer";
import { NLChartPanel } from "@/components/chart/NLChartPanel";
import { SaveChartButton } from "@/components/chart/SaveChartButton";
import { AddToDashboard } from "@/components/dashboard/AddToDashboard";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Spinner } from "@/components/ui/spinner";
import { EmptyState } from "@/components/ui/empty-state";
import { humanize } from "@/lib/format";
import type {
  ChartOptions,
  ChartSort,
  ChartSpec,
  ChartType,
  NLChartResponse,
  NumberFormat,
  SemanticGranularity,
  SemanticQueryRequest,
} from "@/types/api";

const CHART_TYPES: ChartType[] = [
  "bar",
  "hbar",
  "line",
  "area",
  "combo",
  "pie",
  "donut",
  "scatter",
  "funnel",
  "treemap",
  "radar",
  "gauge",
  "table",
  "number",
];
const GRANULARITIES: SemanticGranularity[] = ["day", "week", "month", "quarter", "year"];
const SORTS: ChartSort[] = ["none", "value_desc", "value_asc", "label_asc", "label_desc"];
const DEFAULT_LIMIT = 50;

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

export function Builder() {
  const semantic = useSemanticBuilder();

  const [aiResult, setAiResult] = useState<NLChartResponse | null>(null);

  return (
    <div className="animate-in-up">
      <PageHeader
        title="Chart builder"
        description="Point-and-click to build a chart on a governed semantic model, or describe one in plain English. Format it, then save the result."
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[320px_1fr]">
        <Card className="bg-card/70 lg:sticky lg:top-20 lg:self-start">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <SlidersHorizontal className="h-4 w-4" aria-hidden />
              Configure
            </CardTitle>
            <CardDescription>Map a governed model to a chart, then format it.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <SemanticControls s={semantic} />
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
        </div>
      </div>
    </div>
  );
}

// ===========================================================================
// Semantic-model path
// ===========================================================================

type SemanticBuilder = ReturnType<typeof useSemanticBuilder>;

function useSemanticBuilder() {
  const { data: models, isLoading: modelsLoading } = useSemanticModels();

  const [modelName, setModelName] = useState("");
  const [dimension, setDimension] = useState("");
  const [measure, setMeasure] = useState("");
  const [granularity, setGranularity] = useState<SemanticGranularity>("month");
  const [chartType, setChartType] = useState<ChartType>("bar");
  const [format, setFormat] = useState<FormatState>(DEFAULT_FORMAT);

  const model = models?.find((m) => m.name === modelName) ?? models?.[0];
  const effDimension = dimension || model?.dimensions[0]?.name || "";
  const effMeasure = measure || model?.measures[0]?.name || "";
  const ready = !!model && !!effDimension && !!effMeasure;

  // A `time`-typed dimension is grouped via Cube's timeDimensions with a granularity;
  // the rolled-up column the chart plots is keyed `<dimension>.<granularity>`.
  const isTimeDimension =
    model?.dimensions.find((d) => d.name === effDimension)?.type === "time";
  const timeDimensions = isTimeDimension ? [{ dimension: effDimension, granularity }] : [];
  const xField = isTimeDimension ? `${effDimension}.${granularity}` : effDimension;

  const request: SemanticQueryRequest | null = ready
    ? isTimeDimension
      ? {
          measures: [effMeasure],
          dimensions: [],
          time_dimensions: timeDimensions,
          limit: DEFAULT_LIMIT,
        }
      : { measures: [effMeasure], dimensions: [effDimension], limit: DEFAULT_LIMIT }
    : null;
  const result = useSemanticQuery(request);

  const measureLabel = model?.measures.find((m) => m.name === effMeasure)?.title ?? effMeasure;
  const dimLabel = model?.dimensions.find((d) => d.name === effDimension)?.title ?? effDimension;
  const title = `${measureLabel} by ${dimLabel}${isTimeDimension ? ` (${granularity})` : ""}`;

  const spec: ChartSpec = {
    version: "1",
    type: chartType,
    query: {
      metric_refs: [effMeasure],
      ...(isTimeDimension ? { time_dimensions: timeDimensions } : {}),
    },
    encoding: {
      x: xField || null,
      series: [{ field: effMeasure, name: measureLabel }],
    },
    options: toChartOptions(title, format),
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
    isTimeDimension,
    granularity,
    setGranularity,
    chartType,
    setChartType,
    format,
    setFormat,
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
        No semantic models are available yet. Create one over a data mart, then come back
        to build a chart on it.
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

      {s.isTimeDimension && (
        <div className="space-y-1.5">
          <Label htmlFor="b-sem-gran">Granularity</Label>
          <Select
            id="b-sem-gran"
            value={s.granularity}
            onChange={(e) => s.setGranularity(e.target.value as SemanticGranularity)}
          >
            {GRANULARITIES.map((g) => (
              <option key={g} value={g}>
                {humanize(g)}
              </option>
            ))}
          </Select>
        </div>
      )}

      <div className="space-y-1.5">
        <Label htmlFor="b-sem-measure">Measure</Label>
        <Select id="b-sem-measure" value={s.measure} onChange={(e) => s.setMeasure(e.target.value)}>
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

      <FormatControls format={s.format} setFormat={s.setFormat} />
    </>
  );
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
