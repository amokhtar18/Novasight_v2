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

import { useEffect, useRef } from "react";

// Tree-shaken ECharts imports — only load what we use.
import * as echarts from "echarts/core";
import { BarChart, LineChart, PieChart } from "echarts/charts";
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
  TitleComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsOption } from "echarts";

import type { ChartSpec, QueryResponse } from "@/types/api";

// Register only what we use.
echarts.use([
  BarChart,
  LineChart,
  PieChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  TitleComponent,
  CanvasRenderer,
]);

// ---------------------------------------------------------------------------
// Spec → ECharts option mapping
// ---------------------------------------------------------------------------

/**
 * Map a ChartSpec + QueryResponse into an ECharts option object.
 * Exported so it can be unit-tested without a DOM.
 */
export function buildEChartsOption(
  spec: ChartSpec,
  data: QueryResponse
): EChartsOption {
  const { columns, rows } = data;
  const { x, series } = spec.encoding;
  const options = spec.options ?? {};
  const showLegend = options.show_legend ?? true;

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

  // Legend label for a series: explicit name, else the field name.
  const seriesLabel = (s: ChartSpec["encoding"]["series"][number]): string =>
    s.name ?? s.field;

  if (spec.type === "table") {
    // Tables are not an ECharts option; the renderer presents them separately.
    throw new Error("table charts are rendered without ECharts (see Task 3.2)");
  }

  if (x === null || x === undefined) {
    throw new Error(`chart type "${spec.type}" requires encoding.x`);
  }
  const xIdx = colIndex(x);

  const categories = rows.map((row) => {
    const val = row[xIdx];
    return val === null || val === undefined ? "(null)" : String(val);
  });

  if (spec.type === "pie") {
    const seriesSpec = series[0];
    if (!seriesSpec) throw new Error("Pie chart requires at least one series");
    const valIdx = colIndex(seriesSpec.field);

    return {
      title: options.title ? { text: options.title } : undefined,
      tooltip: { trigger: "item" },
      legend: showLegend ? { orient: "vertical", left: "left" } : undefined,
      series: [
        {
          name: seriesLabel(seriesSpec),
          type: "pie",
          radius: "60%",
          data: rows.map((row) => ({
            name:
              row[xIdx] === null || row[xIdx] === undefined
                ? "(null)"
                : String(row[xIdx]),
            value: row[valIdx] === null ? 0 : (row[valIdx] as number),
          })),
          emphasis: {
            itemStyle: {
              shadowBlur: 10,
              shadowOffsetX: 0,
              shadowColor: "rgba(0, 0, 0, 0.5)",
            },
          },
        },
      ],
    };
  }

  // bar | line | area  ("area" is a line series with an areaStyle)
  const isArea = spec.type === "area";
  const seriesList = series.map((s) => {
    const valIdx = colIndex(s.field);
    return {
      name: seriesLabel(s),
      type: (isArea ? "line" : spec.type) as "bar" | "line",
      stack: options.stacked ? "total" : undefined,
      areaStyle: isArea ? {} : undefined,
      itemStyle: s.color ? { color: s.color } : undefined,
      data: rows.map((row) =>
        row[valIdx] === null ? 0 : (row[valIdx] as number)
      ),
    };
  });

  return {
    title: options.title ? { text: options.title } : undefined,
    tooltip: { trigger: "axis" },
    legend: showLegend ? { data: series.map(seriesLabel) } : undefined,
    xAxis: {
      type: "category",
      name: options.x_axis_label ?? undefined,
      data: categories,
      axisLabel: { rotate: categories.length > 6 ? 45 : 0 },
    },
    yAxis: { type: "value", name: options.y_axis_label ?? undefined },
    series: seriesList,
  };
}

// ---------------------------------------------------------------------------
// React component
// ---------------------------------------------------------------------------

interface ChartRendererProps {
  spec: ChartSpec;
  data: QueryResponse;
  /** Optional accessible title for the chart region. */
  title?: string;
  className?: string;
}

/**
 * Renders a chart described by `spec` using `data` from the query endpoint.
 * The chart is responsive: it listens to container resize via ResizeObserver.
 */
export function ChartRenderer({
  spec,
  data,
  title,
  className = "",
}: ChartRendererProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  // Initialise chart instance on mount.
  useEffect(() => {
    if (!containerRef.current) return;
    const instance = echarts.init(containerRef.current);
    chartRef.current = instance;

    const observer = new ResizeObserver(() => {
      instance.resize();
    });
    observer.observe(containerRef.current);

    return () => {
      observer.disconnect();
      instance.dispose();
      chartRef.current = null;
    };
  }, []);

  // Update chart option whenever spec or data changes.
  useEffect(() => {
    if (!chartRef.current) return;
    try {
      const option = buildEChartsOption(spec, data);
      chartRef.current.setOption(option, true /* notMerge */);
    } catch (err) {
      console.error("[ChartRenderer] Failed to build chart option:", err);
    }
  }, [spec, data]);

  return (
    <div
      ref={containerRef}
      role="img"
      aria-label={title ?? `${spec.type} chart`}
      className={`w-full h-80 ${className}`}
    />
  );
}
