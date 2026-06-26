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
  HeatmapChart,
  LineChart,
  PieChart,
  RadarChart,
  SankeyChart,
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
  VisualMapComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsOption } from "echarts";

import { readChartTheme, type ChartTheme } from "@/lib/chartTheme";
import { applyBreakdown } from "@/lib/chartPivot";
import { useTheme } from "@/lib/theme";
import { TableRenderer } from "@/components/chart/TableRenderer";
import { NumberRenderer } from "@/components/chart/NumberRenderer";
import { formatChartValue } from "@/lib/chartFormat";
import { COLOR_SCHEMES } from "@/lib/colorSchemes";
import type { CartesianOptions, ChartSpec, ChartSort, QueryResponse, SelectionPair } from "@/types/api";

// Register only what we use (v2 adds funnel/gauge/radar/treemap, #8; Slice D adds heatmap + sankey).
echarts.use([
  BarChart,
  LineChart,
  PieChart,
  ScatterChart,
  FunnelChart,
  GaugeChart,
  RadarChart,
  TreemapChart,
  HeatmapChart,
  SankeyChart,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  RadarComponent,
  TooltipComponent,
  TitleComponent,
  VisualMapComponent,
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

/** Heatmap: x dimension × y dimension (breakdown[0]) grid, measure → cell colour. */
function buildHeatmapOption(
  spec: ChartSpec,
  data: QueryResponse,
  theme: ChartTheme
): EChartsOption {
  const h = spec.options?.type_options?.heatmap ?? {};
  const xCol = spec.encoding.x as string;
  const yCol = (spec.encoding.breakdown ?? [])[0];
  const vCol = spec.encoding.series[0].field;
  const xIdx = data.columns.indexOf(xCol);
  const yIdx = yCol != null ? data.columns.indexOf(yCol) : -1;
  const vIdx = data.columns.indexOf(vCol);
  if (xIdx < 0 || yIdx < 0 || vIdx < 0) {
    throw new Error("heatmap requires x, breakdown[0], and a measure present in the data");
  }
  const xs: string[] = [];
  const ys: string[] = [];
  for (const r of data.rows) {
    const xv = String(r[xIdx]);
    const yv = String(r[yIdx]);
    if (!xs.includes(xv)) xs.push(xv);
    if (!ys.includes(yv)) ys.push(yv);
  }
  const cells = data.rows.map((r) => [
    xs.indexOf(String(r[xIdx])),
    ys.indexOf(String(r[yIdx])),
    Number(r[vIdx] ?? 0) || 0,
  ]);
  const values = cells.map((c) => c[2] as number);
  const fmt = (v: number) => formatChartValue(v, spec.options?.number_format);
  return {
    tooltip: { position: "top" },
    grid: { containLabel: true, left: 8, right: 8, top: 8, bottom: 8 },
    xAxis: { type: "category", data: xs, axisLabel: { color: theme.text } },
    yAxis: { type: "category", data: ys, axisLabel: { color: theme.text } },
    visualMap: {
      min: h.value_min ?? Math.min(0, ...values),
      max: h.value_max ?? Math.max(0, ...values),
      calculable: true,
      orient: "horizontal",
      left: "center",
      bottom: 0,
      show: h.show_visual_map !== false,
      inRange: { color: [h.min_color ?? "#e0f2fe", h.max_color ?? "#0369a1"] },
      textStyle: { color: theme.text },
    },
    series: [
      {
        type: "heatmap",
        data: cells,
        label: { show: h.show_values === true, formatter: (p: any) => fmt(Number(p.value[2])) },
        itemStyle: h.cell_border ? { borderColor: theme.axisLine, borderWidth: 1 } : undefined,
      },
    ],
  } as EChartsOption;
}

/** Sankey: links from each x value to each y value (breakdown[0]), weighted by the measure. */
function buildSankeyOption(
  spec: ChartSpec,
  data: QueryResponse,
  theme: ChartTheme
): EChartsOption {
  const s = spec.options?.type_options?.sankey ?? {};
  const xIdx = data.columns.indexOf(spec.encoding.x as string);
  const yIdx = data.columns.indexOf((spec.encoding.breakdown ?? [])[0]);
  const vIdx = data.columns.indexOf(spec.encoding.series[0].field);
  if (xIdx < 0 || yIdx < 0 || vIdx < 0) {
    throw new Error("sankey requires x, breakdown[0], and a measure present in the data");
  }
  // Disjoint node id namespaces: a target that shares an x value gets a suffix so links
  // stay acyclic; the label strips the suffix for display.
  const names = new Set<string>();
  const nodes: { name: string }[] = [];
  const addNode = (name: string) => {
    if (!names.has(name)) {
      names.add(name);
      nodes.push({ name });
    }
  };
  const links = data.rows.map((r) => {
    const src = String(r[xIdx]);
    let tgt = String(r[yIdx]);
    if (src === tgt) tgt += "\u200B"; // zero-width suffix to break a self-cycle
    addNode(src);
    addNode(tgt);
    return { source: src, target: tgt, value: Number(r[vIdx] ?? 0) || 0 };
  });
  return {
    tooltip: { trigger: "item" },
    series: [
      {
        type: "sankey",
        orient: s.orient ?? "horizontal",
        nodeAlign: s.node_align ?? "justify",
        nodeWidth: s.node_width ?? 20,
        nodeGap: s.node_gap ?? 8,
        data: nodes,
        links,
        label: { show: s.show_labels !== false, color: theme.text,
          formatter: (p: any) => String(p.name).replace(/\u200B/g, "") },
        lineStyle: { color: s.link_color ?? "gradient", opacity: 0.4 },
      },
    ],
  } as EChartsOption;
}

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

  // Legend
  const legend = opts.legend ?? {};
  const showLegend = legend.show ?? true;

  // Labels
  const labels = opts.labels ?? {};

  // Tooltip
  const tip = opts.tooltip ?? {};

  // Resolve palette: explicit > color_scheme named palette > theme default.
  const palette =
    opts.palette && opts.palette.length > 0
      ? opts.palette
      : opts.color_scheme
        ? (COLOR_SCHEMES[opts.color_scheme] ?? theme.palette)
        : theme.palette;
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

  if (spec.type === "heatmap") {
    return buildHeatmapOption(spec, data, theme);
  }

  if (spec.type === "sankey") {
    return buildSankeyOption(spec, data, theme);
  }

  const titleBlock = opts.title
    ? { text: opts.title, textStyle: { color: theme.text } }
    : undefined;

  // Shared legend block — reads from opts.legend.{show,position,type,margin,sort}
  const legendBlock = (): Record<string, unknown> | undefined => {
    if (!showLegend) return undefined;
    const pos = legend.position ?? "top";
    // A1: legend.sort — ECharts has no native sort prop; sort the data array.
    const rawLabels = series.map(seriesLabel);
    const legendData =
      legend.sort === "asc"
        ? [...rawLabels].sort((a, b) => a.localeCompare(b))
        : legend.sort === "desc"
          ? [...rawLabels].sort((a, b) => b.localeCompare(a))
          : rawLabels;
    const base: Record<string, unknown> = {
      data: legendData,
      textStyle: { color: theme.text },
      type: legend.type === "plain" ? "plain" : "scroll",
      ...(legend.margin != null ? { padding: legend.margin } : {}),
    };
    if (pos === "bottom") return { ...base, bottom: 0 };
    if (pos === "left") return { ...base, orient: "vertical", left: "left" };
    if (pos === "right") return { ...base, orient: "vertical", right: "right" };
    return { ...base, top: 0 };
  };

  // Shared data label — reads from opts.labels.{show,position,template,threshold}
  // A3: template and threshold for non-pie families.
  const buildDataLabel = (): Record<string, unknown> | undefined => {
    if (!labels.show) return undefined;
    const base: Record<string, unknown> = {
      show: true,
      color: theme.text,
      ...(labels.position ? { position: labels.position } : {}),
    };
    // When threshold is set, hide labels for values below it (compose with template
    // if both are set — threshold wins on hiding).
    if (labels.threshold != null) {
      const tpl = labels.template;
      base.formatter = (params: { value?: number | unknown }) => {
        const v = typeof params === "object" && params !== null
          ? (params as { value?: unknown }).value
          : params;
        if ((v == null ? 0 : Number(v)) < (labels.threshold as number)) return "";
        return tpl ?? String(v ?? "");
      };
    } else if (labels.template) {
      base.formatter = labels.template;
    }
    return base;
  };
  const dataLabel = buildDataLabel();

  // applyDateFmt: apply a strftime-style token format to a date string.
  // Recognises %Y %m %d %H %M with zero-padding. Returns the input unchanged
  // when the format is absent or the string does not parse as a Date.
  const applyDateFmt = (cat: string, fmt: string | null | undefined): string => {
    if (!fmt) return cat;
    const d = new Date(cat);
    if (isNaN(d.getTime())) return cat;
    const pad = (n: number): string => String(n).padStart(2, "0");
    return fmt
      .replace(/%Y/g, String(d.getFullYear()))
      .replace(/%m/g, pad(d.getMonth() + 1))
      .replace(/%d/g, pad(d.getDate()))
      .replace(/%H/g, pad(d.getHours()))
      .replace(/%M/g, pad(d.getMinutes()));
  };

  // dateFmt: applies options.date_format to axis category labels.
  const dateFmt = (cat: string): string => applyDateFmt(cat, opts.date_format);

  // Tooltip trigger — for cartesian families the mode drives axis vs item.
  const tooltipTrigger = tip.mode === "item" ? "item" : "axis";

  // Axis tooltip formatter: handles sort_by_metric (A2), time_format header (A5),
  // show_total, and show_percentage.
  const buildAxisTooltipFormatter = (): ((params: unknown) => string) | undefined => {
    if (!tip.show_total && !tip.show_percentage && !tip.sort_by_metric && !tip.time_format) {
      return undefined;
    }
    return (params: unknown): string => {
      const rawItems = params as Array<{ seriesName: string; value: number; marker: string }>;
      if (!Array.isArray(rawItems) || rawItems.length === 0) return "";
      // A2: sort_by_metric — sort tooltip rows by value descending before rendering.
      const items = tip.sort_by_metric
        ? [...rawItems].sort((a, b) => (Number(b.value) || 0) - (Number(a.value) || 0))
        : rawItems;
      const total = items.reduce((s, p) => s + (Number(p.value) || 0), 0);
      // A5: tooltip.time_format — apply to the axis header value; fall back to date_format.
      const rawHeader = String((items[0] as { axisValue?: string }).axisValue ?? "");
      const header = tip.time_format
        ? applyDateFmt(rawHeader, tip.time_format)
        : dateFmt(rawHeader);
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

  const _axisFormatter = buildAxisTooltipFormatter();
  const axisTooltip = {
    trigger: tooltipTrigger,
    backgroundColor: theme.tooltipBg,
    borderColor: theme.tooltipBorder,
    textStyle: { color: theme.text },
    ...(_axisFormatter != null
      ? { formatter: _axisFormatter }
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
    const g = t.gauge ?? {};
    const maxVal = g.max ?? Math.max(total * 1.25, 1);

    // Build axisLine colour stops: if intervals defined, normalise each bound to [0..1]
    // over maxVal and pair with its colour (fall back to palette[i] if colour missing).
    const axisLineColor: [number, string][] =
      Array.isArray(g.intervals) && g.intervals.length > 0
        ? (g.intervals as number[]).map((bound: number, i: number) => [
            Math.min(bound / maxVal, 1),
            (Array.isArray(g.interval_colors) && g.interval_colors[i] != null
              ? g.interval_colors[i]
              : palette[i] ?? theme.axisLine) as string,
          ])
        : [[1, theme.axisLine as string]];

    return toOption({
      color: palette,
      textStyle: { color: theme.text },
      title: titleBlock,
      animation: g.animation ?? true,
      series: [
        {
          type: "gauge",
          min: g.min ?? 0,
          max: maxVal,
          ...(g.start_angle != null ? { startAngle: g.start_angle as number } : {}),
          ...(g.end_angle != null ? { endAngle: g.end_angle as number } : {}),
          pointer: { show: g.show_pointer ?? true },
          progress: { show: g.show_progress ?? false, roundCap: g.round_cap ?? false },
          axisTick: { show: g.show_axis_tick ?? false },
          splitLine: { show: g.show_split_line ?? false },
          ...(g.split_number != null ? { splitNumber: g.split_number as number } : {}),
          axisLine: { lineStyle: { color: axisLineColor } },
          axisLabel: { color: theme.text, formatter: (v: number) => fmt(v) },
          detail: {
            formatter: (v: number) => fmt(v),
            color: theme.text,
            ...(g.font_size != null ? { fontSize: g.font_size as number } : {}),
          },
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
    const p = t.pie ?? {};

    // Build raw slice data from sorted rows.
    const rawSlices = srows.map((row, i) => ({ name: categories[i], value: num(row[valIdx]) }));

    // Fold slices below group_others_threshold (as % of total) into a single "Other" datum.
    let sliceData: Array<{ name: string; value: number }>;
    if (p.group_others_threshold != null && p.group_others_threshold > 0) {
      const total = rawSlices.reduce((acc, s) => acc + s.value, 0);
      if (total > 0) {
        let othersSum = 0;
        const kept: Array<{ name: string; value: number }> = [];
        for (const s of rawSlices) {
          if ((s.value / total) * 100 < p.group_others_threshold) {
            othersSum += s.value;
          } else {
            kept.push(s);
          }
        }
        sliceData = othersSum > 0 ? [...kept, { name: "Other", value: othersSum }] : kept;
      } else {
        sliceData = rawSlices;
      }
    } else {
      sliceData = rawSlices;
    }

    // Radius: [inner, outer] — donut default inner 50, pie 0.
    const innerR = p.inner_radius ?? (spec.type === "donut" ? 50 : 0);
    const outerR = p.outer_radius ?? 70;
    const radius: [string, string] = [`${innerR}%`, `${outerR}%`];

    // roseType: omit (undefined) when not set or "none".
    const roseType =
      p.rose_type && p.rose_type !== "none" ? (p.rose_type as "area" | "radius") : undefined;

    // Label position & line.
    const labelPosition = p.labels_outside ? "outside" : "inside";
    const labelLineShow = p.label_line ?? (p.labels_outside ? true : false);

    // Label formatter from label_type + shared labels.template.
    const buildLabelFormatter = (): string | undefined => {
      const tpl = labels.template;
      if (tpl) return tpl;
      const lt = p.label_type;
      if (!lt) return undefined;
      switch (lt) {
        case "category":              return "{b}";
        case "value":                 return "{c}";
        case "percent":               return "{d}%";
        case "category_value":        return "{b}: {c}";
        case "value_percent":         return "{c} ({d}%)";
        case "category_value_percent": return "{b}: {c} ({d}%)";
        default:                      return undefined;
      }
    };
    const labelFormatter = buildLabelFormatter();

    // show_labels_threshold: hide labels when slice < threshold %, else show.
    // ECharts label.show can be a callback but that is complex; use formatter to blank out.
    const showLabelsThreshold = p.show_labels_threshold ?? null;
    const labelConfig: Record<string, unknown> = {
      show: labels.show !== false,
      color: theme.text,
      position: labelPosition,
      ...(labelFormatter ? { formatter: labelFormatter } : {}),
    };
    if (showLabelsThreshold != null && showLabelsThreshold > 0) {
      // Blank the label text for slices below the threshold percentage.
      labelConfig.formatter = (params: { percent?: number }) => {
        const pct = params.percent ?? 0;
        if (pct < showLabelsThreshold) return "";
        return labelFormatter ?? "{b}";
      };
    }

    // show_total: sum of all slice values, rendered as a centered title/graphic.
    const pieTotal = sliceData.reduce((acc, s) => acc + s.value, 0);
    let totalBlock: Record<string, unknown> | undefined;
    let graphicBlock: unknown[] | undefined;
    if (p.show_total) {
      const totalText = fmt(pieTotal);
      if (!opts.title) {
        // No chart title — use ECharts title for the center total.
        totalBlock = {
          text: totalText,
          left: "center",
          top: "center",
          textStyle: { color: theme.text, fontSize: 18, fontWeight: "bold" },
        };
      } else {
        // Chart title already occupies the title slot — use a graphic element.
        graphicBlock = [
          {
            type: "text",
            left: "center",
            top: "center",
            style: { text: totalText, fill: theme.text, fontSize: 18, fontWeight: "bold" },
          },
        ];
      }
    }

    return toOption({
      color: palette,
      textStyle: { color: theme.text },
      title: totalBlock ?? titleBlock,
      tooltip: itemTooltip,
      legend: legendBlock(),
      ...(graphicBlock ? { graphic: graphicBlock } : {}),
      series: [
        {
          name: seriesLabel(seriesSpec),
          type: "pie",
          radius,
          ...(roseType ? { roseType } : {}),
          itemStyle: { borderColor: theme.tooltipBg, borderWidth: 2 },
          label: labelConfig,
          labelLine: { show: labelLineShow },
          data: sliceData,
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
    const f = t.funnel ?? {};

    // Map funnel label_type to an ECharts formatter string.
    const funnelLabelFormatter = (lt: string | undefined): string | undefined => {
      switch (lt) {
        case "none":            return "";
        case "value":           return "{c}";
        case "percent":         return "{d}%";
        case "category":        return "{b}";
        case "category_value":  return "{b}: {c}";
        case "value_percent":   return "{c} ({d}%)";
        case "all":             return "{b}: {c} ({d}%)";
        default:                return undefined;
      }
    };

    const funnelLabelShow = f.show_labels ?? true;
    const funnelFormatter = funnelLabelFormatter(f.label_type);

    // Funnel tooltip: when show_tooltip_labels is true (default) and
    // tooltip_label_type is set, build a formatter that renders the chosen
    // content variant. When show_tooltip_labels is false, suppress labels in
    // the tooltip by returning only the series name (no value/percent).
    const showTooltipLabels = f.show_tooltip_labels ?? true;
    const tooltipFormatter = showTooltipLabels
      ? (funnelLabelFormatter(f.tooltip_label_type) ?? undefined)
      : undefined;
    const funnelTooltip = showTooltipLabels
      ? {
          ...itemTooltip,
          ...(tooltipFormatter != null ? { formatter: tooltipFormatter } : {}),
        }
      : {
          ...itemTooltip,
          formatter: "{b}",
        };

    return toOption({
      color: palette,
      textStyle: { color: theme.text },
      title: titleBlock,
      tooltip: funnelTooltip,
      legend: legendBlock(),
      series: [
        {
          type: "funnel",
          left: "10%",
          right: "10%",
          label: {
            show: funnelLabelShow,
            color: theme.text,
            ...(funnelFormatter != null ? { formatter: funnelFormatter } : {}),
          },
          data: srows.map((row, i) => ({ name: categories[i], value: num(row[valIdx]) })),
        },
      ],
    });
  }

  // ---- Treemap. -------------------------------------------------------
  if (spec.type === "treemap") {
    const valIdx = colIndex(series[0].field);
    const tm = t.treemap ?? {};

    // Map treemap label_type to an ECharts formatter string.
    const treemapLabelFormatter = (lt: string | undefined): string | undefined => {
      switch (lt) {
        case "key":       return "{b}";
        case "value":     return "{c}";
        case "key_value": return "{b}: {c}";
        default:          return undefined;
      }
    };

    const tmFormatter = treemapLabelFormatter(tm.label_type);

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
          label: {
            show: tm.show_labels ?? true,
            color: "#fff",
            ...(tmFormatter != null ? { formatter: tmFormatter } : {}),
          },
          upperLabel: {
            show: tm.show_upper_labels ?? false,
            color: theme.text,
          },
          data: srows.map((row, i) => ({ name: categories[i], value: num(row[valIdx]) })),
        },
      ],
    });
  }

  // ---- Radar: each series is a polygon over the x categories. ---------
  if (spec.type === "radar") {
    const r = t.radar ?? {};
    const valIdxs = series.map((s) => colIndex(s.field));
    const maxVal = Math.max(1, ...valIdxs.flatMap((vi) => srows.map((row) => num(row[vi]))));

    // Build per-indicator max/min: when metric_bounds is keyed by category name,
    // look up the bound for that category; otherwise use the computed maxVal.
    // metric_bounds is keyed by category (x-axis value) in the current data model.
    const metricBounds = r.metric_bounds ?? {};
    const indicator = categories.map((c) => {
      const bound = metricBounds[c];
      return {
        name: c,
        max: (bound?.max != null ? bound.max : maxVal) as number,
        ...(bound?.min != null ? { min: bound.min as number } : {}),
      };
    });

    // Radar series label formatter.
    const radarLabelFormatter = (lt: string | undefined): string | undefined => {
      switch (lt) {
        case "value":          return "{c}";
        case "category_value": return "{b}: {c}";
        default:               return undefined;
      }
    };

    const radarFormatter = radarLabelFormatter(r.label_type);
    const radarSeriesLabel = r.label_type
      ? {
          show: true,
          color: theme.text,
          ...(radarFormatter != null ? { formatter: radarFormatter } : {}),
          ...(r.label_position ? { position: r.label_position } : {}),
        }
      : undefined;

    return toOption({
      color: palette,
      textStyle: { color: theme.text },
      title: titleBlock,
      tooltip: itemTooltip,
      legend: legendBlock(),
      radar: {
        shape: (r.shape ?? "polygon") as "circle" | "polygon",
        indicator,
        axisName: { color: theme.text },
        splitLine: { lineStyle: { color: theme.axisLine } },
      },
      series: [
        {
          type: "radar",
          ...(radarSeriesLabel ? { label: radarSeriesLabel } : {}),
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
      xAxis: valueAxis(theme, c, fmt, c.x_axis_label ?? undefined),
      yAxis: {
        type: "category",
        data: categories,
        axisLabel: { color: theme.text },
        axisLine: { lineStyle: { color: theme.axisLine } },
        minorTick: { show: c.minor_ticks ?? false },
        minorSplitLine: { show: c.minor_split_line ?? false },
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
      showSymbol: seriesType === "line" ? (c.markers ?? undefined) : undefined,
      symbolSize: seriesType === "line" ? (c.marker_size ?? undefined) : undefined,
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
      minorSplitLine: { show: c.minor_split_line ?? false },
      nameTextStyle: { color: theme.text },
    },
    yAxis: valueAxis(theme, c, fmt, c.y_axis_label),
    series: seriesList,
  });
}

// ---------------------------------------------------------------------------
// React component
// ---------------------------------------------------------------------------

/** Map an ECharts click to cross-filter pairs. Category charts emit one pair on `x`. */
function selectionPairsFromClick(
  spec: ChartSpec,
  params: Record<string, unknown>
): SelectionPair[] {
  const name = params.name as string | undefined;
  if (name && spec.encoding.x) {
    return [{ member: spec.encoding.x, value: String(name) }];
  }
  return [];
}

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
   * Called with (member, value) pairs when the user clicks a data point on a
   * category-axis chart (bar/line/area/pie). Used for dashboard cross-filtering.
   * Never fires for value-axis (scatter) or non-ECharts (table/number) renders.
   */
  onSelectPoints?: (pairs: SelectionPair[]) => void;
}

/**
 * Renders a chart described by `spec` using `data` from the query endpoint.
 * The chart is responsive: it listens to container resize via ResizeObserver.
 */
export const ChartRenderer = forwardRef<ChartRendererHandle, ChartRendererProps>(function ChartRenderer(
  { spec, data, title, className = "", onSelectPoints },
  ref
) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  // Latest select handler, read by the (once-attached) click listener so it never
  // goes stale without re-binding the listener. Updated in an effect (not during
  // render) per react-hooks rules.
  const onSelectRef = useRef(onSelectPoints);
  useEffect(() => {
    onSelectRef.current = onSelectPoints;
  });
  // specRef: keeps the current spec for the click handler (attached once in the
  // mount effect; must read the latest spec without re-disposing the instance).
  const specRef = useRef(spec);
  useEffect(() => {
    specRef.current = spec;
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

    // Cross-filtering: a click on a category-axis point emits governed (member, value)
    // pairs. Reads specRef.current so tile spec changes don't require re-init.
    instance.on("click", (params) => {
      const pairs = selectionPairsFromClick(specRef.current, params as Record<string, unknown>);
      if (pairs.length > 0) onSelectRef.current?.(pairs);
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
