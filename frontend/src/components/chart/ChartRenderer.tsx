/**
 * ChartRenderer — ECharts chart driven by a declarative ChartSpec.
 *
 * The renderer is decoupled from data-fetching: it receives a typed ChartSpec
 * (what to render) and a QueryResponse (raw row data) and maps them into an
 * ECharts option. This means the same renderer works for manually configured
 * charts and AI-generated specs (which share the ChartSpec shape).
 *
 * Only the ECharts modules actually used are imported (keep the bundle lean).
 */

import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";

// Tree-shaken ECharts imports — only load what we use.
import * as echarts from "echarts/core";
import {
  BarChart,
  FunnelChart,
  GaugeChart,
  LineChart,
  PieChart,
  RadarChart,
  ScatterChart,
  TreemapChart,
} from "echarts/charts";
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  RadarComponent,
  TooltipComponent,
  TitleComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsOption } from "echarts";

import { readChartTheme, type ChartTheme } from "@/lib/chartTheme";
import { applyBreakdown } from "@/lib/chartPivot";
import { useTheme } from "@/lib/theme";
import { TableRenderer } from "@/components/chart/TableRenderer";
import { NumberRenderer } from "@/components/chart/NumberRenderer";
import { formatChartValue } from "@/lib/chartFormat";
import type { CartesianOptions, ChartSpec, ChartSort, QueryResponse } from "@/types/api";

// Register only what we use (v2 adds funnel/gauge/radar/treemap, #8).
echarts.use([
  BarChart,
  LineChart,
  PieChart,
  ScatterChart,
  FunnelChart,
  GaugeChart,
  RadarChart,
  TreemapChart,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  RadarComponent,
  TooltipComponent,
  TitleComponent,
  CanvasRenderer,
]);

type Row = QueryResponse["rows"][number];

/** Reorder plotted rows per the spec's sort option (by first value or by x label). */
function sortRows(rows: Row[], xIdx: number, valIdx: number, sort: ChartSort): Row[] {
  if (sort === "none") return rows;
  const arr = [...rows];
  arr.sort((a, b) => {
    if (sort === "value_desc" || sort === "value_asc") {
      const av = Number(a[valIdx] ?? 0) || 0;
      const bv = Number(b[valIdx] ?? 0) || 0;
      return sort === "value_desc" ? bv - av : av - bv;
    }
    const al = a[xIdx] == null ? "" : String(a[xIdx]);
    const bl = b[xIdx] == null ? "" : String(b[xIdx]);
    return sort === "label_desc" ? bl.localeCompare(al) : al.localeCompare(bl);
  });
  return arr;
}

/**
 * A themed value axis honoring number format, bounds, and log scale.
 * Reads from the v2 cartesian type_options group.
 */
function valueAxis(
  theme: ChartTheme,
  cartesian: CartesianOptions | null | undefined,
  fmt: (v: number) => string,
  label?: string | null
): Record<string, unknown> {
  return {
    type: cartesian?.log_scale ? "log" : "value",
    name: label ?? undefined,
    min: cartesian?.log_scale ? undefined : (cartesian?.y_min ?? undefined),
    max: cartesian?.y_max ?? undefined,
    axisLabel: { color: theme.text, formatter: (v: number) => fmt(v) },
    splitLine: { lineStyle: { color: theme.axisLine, opacity: 0.5 } },
    nameTextStyle: { color: theme.text },
  };
}

// ---------------------------------------------------------------------------
// Spec → ECharts option mapping
// ---------------------------------------------------------------------------

/**
 * Map a ChartSpec + QueryResponse into an ECharts option object.
 * Exported so it can be unit-tested without a DOM.
 */
export function buildEChartsOption(
  rawSpec: ChartSpec,
  rawData: QueryResponse,
  theme: ChartTheme = readChartTheme()
): EChartsOption {
  // Pivot any breakdown dimensions into one series column each (no-op when absent),
  // so the rest of this function only ever sees the wide, one-series-per-column form.
  const { spec, data } = applyBreakdown(rawSpec, rawData);
  const { columns, rows } = data;
  const { x, series } = spec.encoding;
  const opts = spec.options ?? {};

  // ---------------------------------------------------------------------------
  // v2 shared chrome derivations
  // ---------------------------------------------------------------------------

  // Per-family type_options accessor — Tasks 5–8 read t.cartesian, t.pie, etc.
  const t = opts.type_options ?? {};

  // Cartesian family options (bar/line/area/hbar/combo/scatter).
  const cartesian = t.cartesian ?? null;

  // Gauge family options.
  const gauge = t.gauge ?? null;

  // Legend
  const legend = opts.legend ?? {};
  const showLegend = legend.show ?? true;

  // Labels
  const labels = opts.labels ?? {};

  // Tooltip
  const tip = opts.tooltip ?? {};

  const palette =
    opts.palette && opts.palette.length > 0 ? opts.palette : theme.palette;
  const fmt = (v: number): string => formatChartValue(v, opts.number_format);
  const num = (v: unknown): number => (v === null || v === undefined ? 0 : Number(v));

  // ECharts' option types are strict-yet-loose; build each option as a plain object
  // and cast at the boundary (the renderer is the only place that touches them).
  const toOption = (o: Record<string, unknown>): EChartsOption => o as EChartsOption;

  // Guard: ensure the referenced columns exist in the response.
  const colIndex = (name: string): number => {
    const idx = columns.indexOf(name);
    if (idx === -1) {
      throw new Error(
        `ChartSpec references column "${name}" but QueryResponse only has: ${columns.join(", ")}`
      );
    }
    return idx;
  };
  const seriesLabel = (s: ChartSpec["encoding"]["series"][number]): string =>
    s.name ?? s.field;

  if (spec.type === "table") {
    throw new Error("table charts are rendered without ECharts (see Task 3.2)");
  }
  if (spec.type === "number") {
    throw new Error("number charts are rendered without ECharts (see NumberRenderer)");
  }

  const titleBlock = opts.title
    ? { text: opts.title, textStyle: { color: theme.text } }
    : undefined;

  // Shared legend block — reads from opts.legend.{show,position,type,margin}
  const legendBlock = (): Record<string, unknown> | undefined => {
    if (!showLegend) return undefined;
    const pos = legend.position ?? "top";
    const base: Record<string, unknown> = {
      data: series.map(seriesLabel),
      textStyle: { color: theme.text },
      type: legend.type === "plain" ? "plain" : "scroll",
      ...(legend.margin != null ? { padding: legend.margin } : {}),
    };
    if (pos === "bottom") return { ...base, bottom: 0 };
    if (pos === "left") return { ...base, orient: "vertical", left: "left" };
    if (pos === "right") return { ...base, orient: "vertical", right: "right" };
    return { ...base, top: 0 };
  };

  // Shared data label — reads from opts.labels.{show,position}
  const dataLabel = labels.show
    ? { show: true, color: theme.text, ...(labels.position ? { position: labels.position } : {}) }
    : undefined;

  // dateFmt: when options.date_format is set and a category string parses as a Date,
  // format it using a minimal token map (%Y %m %d %H %M, zero-padded).
  const dateFmt = (cat: string): string => {
    if (!opts.date_format) return cat;
    const d = new Date(cat);
    if (isNaN(d.getTime())) return cat;
    const pad = (n: number): string => String(n).padStart(2, "0");
    return opts.date_format
      .replace(/%Y/g, String(d.getFullYear()))
      .replace(/%m/g, pad(d.getMonth() + 1))
      .replace(/%d/g, pad(d.getDate()))
      .replace(/%H/g, pad(d.getHours()))
      .replace(/%M/g, pad(d.getMinutes()));
  };

  // Tooltip trigger — for cartesian families the mode drives axis vs item.
  const tooltipTrigger = tip.mode === "item" ? "item" : "axis";

  // Axis tooltip formatter: optionally appends Total and/or per-series percentage
  // when tooltip.show_total or tooltip.show_percentage is set.
  const buildAxisTooltipFormatter = (): ((params: unknown) => string) | undefined => {
    if (!tip.show_total && !tip.show_percentage) return undefined;
    return (params: unknown): string => {
      const items = params as Array<{ seriesName: string; value: number; marker: string }>;
      if (!Array.isArray(items) || items.length === 0) return "";
      const total = items.reduce((s, p) => s + (Number(p.value) || 0), 0);
      const header = dateFmt(String((items[0] as { axisValue?: string }).axisValue ?? ""));
      let html = `${header}<br/>`;
      for (const p of items) {
        const val = fmt(Number(p.value));
        const pct =
          tip.show_percentage && total !== 0
            ? ` (${((Number(p.value) / total) * 100).toFixed(1)}%)`
            : "";
        html += `${p.marker}${p.seriesName}: ${val}${pct}<br/>`;
      }
      if (tip.show_total) {
        html += `<strong>Total: ${fmt(total)}</strong>`;
      }
      return html;
    };
  };

  const axisTooltip = {
    trigger: tooltipTrigger,
    backgroundColor: theme.tooltipBg,
    borderColor: theme.tooltipBorder,
    textStyle: { color: theme.text },
    ...(tip.show_total || tip.show_percentage
      ? { formatter: buildAxisTooltipFormatter() }
      : { valueFormatter: (v: number | string) => fmt(Number(v)) }),
  };

  // Item tooltip always uses trigger "item" — circular families (pie/funnel/treemap/
  // radar/gauge) are not category-axis charts and always need per-point tooltips.
  const itemTooltip = {
    trigger: "item" as const,
    backgroundColor: theme.tooltipBg,
    borderColor: theme.tooltipBorder,
    textStyle: { color: theme.text },
  };

  // ---- Gauge: a single KPI dial (no category axis). --------------------
  if (spec.type === "gauge") {
    const valIdx = colIndex(series[0].field);
    const total = rows.reduce((acc, row) => acc + num(row[valIdx]), 0);
    const maxVal = gauge?.max ?? Math.max(total * 1.25, 1);
    return toOption({
      color: palette,
      textStyle: { color: theme.text },
      title: titleBlock,
      series: [
        {
          type: "gauge",
          min: gauge?.min ?? 0,
          max: maxVal,
          progress: { show: true },
          axisLine: { lineStyle: { color: [[1, theme.axisLine]] } },
          axisLabel: { color: theme.text, formatter: (v: number) => fmt(v) },
          detail: { formatter: (v: number) => fmt(v), color: theme.text },
          title: { color: theme.text },
          data: [{ value: total, name: seriesLabel(series[0]) }],
        },
      ],
    });
  }

  // ---- Scatter: numeric x vs each series' y (value axes). --------------
  if (spec.type === "scatter") {
    if (x === null || x === undefined) throw new Error('chart type "scatter" requires encoding.x');
    const xIdx = colIndex(x);
    const c = t.cartesian ?? {};
    const seriesList = series.map((s) => {
      const yIdx = colIndex(s.field);
      return {
        name: seriesLabel(s),
        type: "scatter" as const,
        symbolSize: c.marker_size ?? undefined,
        itemStyle: s.color ? { color: s.color } : undefined,
        data: rows.map((row) => [num(row[xIdx]), num(row[yIdx])]),
      };
    });
    return toOption({
      color: palette,
      textStyle: { color: theme.text },
      title: titleBlock,
      tooltip: itemTooltip,
      grid: { left: 8, right: 16, top: opts.title ? 48 : 24, bottom: 8, containLabel: true },
      legend: legendBlock(),
      xAxis: valueAxis(theme, cartesian, fmt, cartesian?.x_axis_label),
      yAxis: valueAxis(theme, cartesian, fmt, cartesian?.y_axis_label),
      series: seriesList,
    });
  }

  // Every remaining type needs a category column.
  if (x === null || x === undefined) {
    throw new Error(`chart type "${spec.type}" requires encoding.x`);
  }
  const xIdx = colIndex(x);
  const srows = sortRows(
    rows,
    xIdx,
    series.length ? colIndex(series[0].field) : xIdx,
    opts.sort ?? "none"
  );
  const categories = srows.map((row) =>
    row[xIdx] === null || row[xIdx] === undefined ? "(null)" : dateFmt(String(row[xIdx]))
  );

  // ---- Pie / Donut. ---------------------------------------------------
  if (spec.type === "pie" || spec.type === "donut") {
    const seriesSpec = series[0];
    if (!seriesSpec) throw new Error("Pie chart requires at least one series");
    const valIdx = colIndex(seriesSpec.field);
    return toOption({
      color: palette,
      textStyle: { color: theme.text },
      title: titleBlock,
      tooltip: itemTooltip,
      legend: legendBlock(),
      series: [
        {
          name: seriesLabel(seriesSpec),
          type: "pie",
          radius: spec.type === "donut" ? ["50%", "72%"] : ["42%", "68%"],
          itemStyle: { borderColor: theme.tooltipBg, borderWidth: 2 },
          label: labels.show ? { color: theme.text } : undefined,
          data: srows.map((row, i) => ({ name: categories[i], value: num(row[valIdx]) })),
          emphasis: {
            itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: "rgba(0,0,0,0.5)" },
          },
        },
      ],
    });
  }

  // ---- Funnel. --------------------------------------------------------
  if (spec.type === "funnel") {
    const valIdx = colIndex(series[0].field);
    return toOption({
      color: palette,
      textStyle: { color: theme.text },
      title: titleBlock,
      tooltip: itemTooltip,
      legend: legendBlock(),
      series: [
        {
          type: "funnel",
          left: "10%",
          right: "10%",
          label: { color: theme.text },
          data: srows.map((row, i) => ({ name: categories[i], value: num(row[valIdx]) })),
        },
      ],
    });
  }

  // ---- Treemap. -------------------------------------------------------
  if (spec.type === "treemap") {
    const valIdx = colIndex(series[0].field);
    return toOption({
      color: palette,
      textStyle: { color: theme.text },
      title: titleBlock,
      tooltip: itemTooltip,
      series: [
        {
          type: "treemap",
          roam: false,
          breadcrumb: { show: false },
          label: { color: "#fff" },
          data: srows.map((row, i) => ({ name: categories[i], value: num(row[valIdx]) })),
        },
      ],
    });
  }

  // ---- Radar: each series is a polygon over the x categories. ---------
  if (spec.type === "radar") {
    const valIdxs = series.map((s) => colIndex(s.field));
    const maxVal = Math.max(1, ...valIdxs.flatMap((vi) => srows.map((row) => num(row[vi]))));
    return toOption({
      color: palette,
      textStyle: { color: theme.text },
      title: titleBlock,
      tooltip: itemTooltip,
      legend: legendBlock(),
      radar: {
        indicator: categories.map((c) => ({ name: c, max: maxVal })),
        axisName: { color: theme.text },
        splitLine: { lineStyle: { color: theme.axisLine } },
      },
      series: [
        {
          type: "radar",
          data: series.map((s, si) => ({
            name: seriesLabel(s),
            value: srows.map((row) => num(row[valIdxs[si]])),
          })),
        },
      ],
    });
  }

  // ---- Horizontal bar. ------------------------------------------------
  if (spec.type === "hbar") {
    const c = t.cartesian ?? {};
    const seriesList = series.map((s) => {
      const vi = colIndex(s.field);
      return {
        name: seriesLabel(s),
        type: "bar" as const,
        stack: c.stacked || c.percent ? "total" : undefined,
        itemStyle: s.color ? { color: s.color } : undefined,
        label: dataLabel,
        data: srows.map((row) => num(row[vi])),
      };
    });
    if (c.percent) {
      const totalsPerCat = categories.map((_, i) =>
        seriesList.reduce((acc, s) => acc + (s.data[i] as number), 0) || 1);
      for (const s of seriesList) s.data = (s.data as number[]).map((v, i) => (v / totalsPerCat[i]) * 100);
    }
    return toOption({
      color: palette,
      textStyle: { color: theme.text },
      title: titleBlock,
      tooltip: axisTooltip,
      grid: { left: 8, right: 16, top: opts.title ? 48 : 24, bottom: c.data_zoom ? 48 : 8, containLabel: true },
      legend: legendBlock(),
      ...(c.data_zoom ? { dataZoom: [{ type: "inside" }, { type: "slider" }] } : {}),
      xAxis: valueAxis(theme, cartesian, fmt, c.x_axis_label ?? undefined),
      yAxis: {
        type: "category",
        data: categories,
        axisLabel: { color: theme.text },
        axisLine: { lineStyle: { color: theme.axisLine } },
        minorTick: { show: c.minor_ticks ?? false },
      },
      series: seriesList,
    });
  }

  // ---- Bar / line / area / combo. -------------------------------------
  const c = t.cartesian ?? {};
  const isArea = spec.type === "area";
  const isCombo = spec.type === "combo";

  // sort_series: reorder series by their total (sum across all categories) asc/desc.
  let ordered = series;
  if (c.sort_series && c.sort_series !== "none") {
    const totals = (s: typeof series[number]) =>
      srows.reduce((acc, r) => acc + num(r[colIndex(s.field)]), 0);
    ordered = [...series].sort((a, b) =>
      c.sort_series === "asc" ? totals(a) - totals(b) : totals(b) - totals(a));
  }

  const seriesList = ordered.map((s, si) => {
    const valIdx = colIndex(s.field);
    const seriesType = isCombo
      ? si === 0 ? "bar" : "line"
      : isArea || spec.type === "line" ? "line" : "bar";
    return {
      name: seriesLabel(s),
      type: seriesType as "bar" | "line",
      stack: c.stacked || c.percent ? "total" : undefined,
      areaStyle: isArea ? { opacity: c.area_opacity ?? 0.5 } : undefined,
      smooth: c.smooth || undefined,
      showSymbol: seriesType === "line" ? (c.markers ?? false) : undefined,
      symbolSize: c.marker_size ?? undefined,
      itemStyle: s.color ? { color: s.color } : undefined,
      label: c.only_total && si === ordered.length - 1
        ? { show: true, position: "top", color: theme.text }
        : dataLabel,
      data: srows.map((row) => num(row[valIdx])),
    };
  });

  // percent: normalise per-category totals to 100%.
  if (c.percent) {
    const totalsPerCat = categories.map((_, i) =>
      seriesList.reduce((acc, s) => acc + (s.data[i] as number), 0) || 1);
    for (const s of seriesList) s.data = (s.data as number[]).map((v, i) => (v / totalsPerCat[i]) * 100);
  }

  return toOption({
    color: palette,
    textStyle: { color: theme.text },
    title: titleBlock,
    tooltip: axisTooltip,
    grid: { left: 8, right: 16, top: opts.title ? 48 : 24, bottom: c.data_zoom ? 48 : 8, containLabel: true },
    legend: legendBlock(),
    ...(c.data_zoom ? { dataZoom: [{ type: "inside" }, { type: "slider" }] } : {}),
    xAxis: {
      type: "category",
      name: c.x_axis_label ?? undefined,
      data: categories,
      axisLabel: {
        rotate: c.x_label_rotation ?? (categories.length > 6 ? 45 : 0),
        interval: c.x_label_interval === "all" ? 0 : "auto",
        color: theme.text,
      },
      axisLine: { lineStyle: { color: theme.axisLine } },
      minorTick: { show: c.minor_ticks ?? false },
      nameTextStyle: { color: theme.text },
    },
    yAxis: valueAxis(theme, c, fmt, c.y_axis_label),
    series: seriesList,
  });
}

// ---------------------------------------------------------------------------
// React component
// ---------------------------------------------------------------------------

export interface ChartRendererHandle {
  /** PNG data URL of the current chart, or null for non-ECharts renders. */
  toPng: () => string | null;
}

interface ChartRendererProps {
  spec: ChartSpec;
  data: QueryResponse;
  /** Optional accessible title for the chart region. */
  title?: string;
  className?: string;
  /**
   * Called with the clicked category when the user clicks a data point on a
   * category-axis chart (bar/line/area/pie). Used for dashboard cross-filtering.
   * Never fires for value-axis (scatter) or non-ECharts (table/number) renders.
   */
  onSelectCategory?: (category: string) => void;
}

/**
 * Renders a chart described by `spec` using `data` from the query endpoint.
 * The chart is responsive: it listens to container resize via ResizeObserver.
 */
export const ChartRenderer = forwardRef<ChartRendererHandle, ChartRendererProps>(function ChartRenderer(
  { spec, data, title, className = "", onSelectCategory },
  ref
) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  // Latest select handler, read by the (once-attached) click listener so it never
  // goes stale without re-binding the listener. Updated in an effect (not during
  // render) per react-hooks rules.
  const onSelectRef = useRef(onSelectCategory);
  useEffect(() => {
    onSelectRef.current = onSelectCategory;
  });
  // Re-theme charts when the user flips light/dark.
  const { resolvedTheme } = useTheme();

  useImperativeHandle(
    ref,
    () => ({
      toPng: () =>
        chartRef.current
          ? chartRef.current.getDataURL({ type: "png", pixelRatio: 2, backgroundColor: "transparent" })
          : null,
    }),
    []
  );

  // Table + number tiles are rendered without ECharts (see below).
  const isEcharts = spec.type !== "table" && spec.type !== "number";

  // Initialise chart instance on mount (skip for non-ECharts specs).
  useEffect(() => {
    if (!isEcharts || !containerRef.current) return;
    const instance = echarts.init(containerRef.current);
    chartRef.current = instance;

    // Cross-filtering: a click on a category-axis point reports its category. Pie
    // slices and bar/line/area categories carry a `name`; scatter points don't.
    instance.on("click", (params) => {
      const name = (params as { name?: string }).name;
      if (name && onSelectRef.current) onSelectRef.current(String(name));
    });

    const observer = new ResizeObserver(() => {
      instance.resize();
    });
    observer.observe(containerRef.current);

    return () => {
      observer.disconnect();
      instance.dispose();
      chartRef.current = null;
    };
  }, [isEcharts]);

  // Update chart option whenever spec, data, or theme changes.
  useEffect(() => {
    if (!isEcharts || !chartRef.current) return;
    try {
      const option = buildEChartsOption(spec, data, readChartTheme());
      chartRef.current.setOption(option, true /* notMerge */);
    } catch (err) {
      console.error("[ChartRenderer] Failed to build chart option:", err);
    }
  }, [spec, data, resolvedTheme, isEcharts]);

  if (spec.type === "table") {
    return <TableRenderer spec={spec} data={data} className={className} />;
  }
  if (spec.type === "number") {
    return <NumberRenderer spec={spec} data={data} className={className} />;
  }

  return (
    <div
      ref={containerRef}
      role="img"
      aria-label={title ?? `${spec.type} chart`}
      className={`w-full h-80 ${className}`}
    />
  );
});
