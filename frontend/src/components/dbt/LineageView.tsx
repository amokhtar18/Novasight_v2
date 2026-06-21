/**
 * LineageView — render the tenant's dbt dependency DAG (#5).
 *
 * Pulls the graph from GET /dbt-models/lineage (derived in-app from ref()/source())
 * and lays it out left→right by dependency depth using an ECharts ``graph`` series.
 * Nodes are coloured by kind (model / source / external) and edges point downstream.
 */

import { useEffect, useMemo, useRef } from "react";

import * as echarts from "echarts/core";
import { GraphChart } from "echarts/charts";
import { TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsOption } from "echarts";
import { Network } from "lucide-react";

import { useDbtLineage } from "@/api/hooks";
import { readChartTheme } from "@/lib/chartTheme";
import { useTheme } from "@/lib/theme";
import { Spinner } from "@/components/ui/spinner";
import { EmptyState } from "@/components/ui/empty-state";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import type { LineageGraph } from "@/types/api";

echarts.use([GraphChart, TooltipComponent, CanvasRenderer]);

const COL_GAP = 240;
const ROW_GAP = 76;

/** Colour per node kind, drawn from the active chart theme palette + a muted grey. */
function colorForKind(kind: string, palette: string[]): string {
  if (kind === "source") return palette[2] ?? "#22c55e";
  if (kind === "external") return "#94a3b8";
  return palette[0] ?? "#6366f1";
}

/** Position each node by its longest-path depth (x) and its index within that depth (y). */
function layout(graph: LineageGraph): Map<string, { x: number; y: number }> {
  const incoming = new Map<string, string[]>();
  for (const n of graph.nodes) incoming.set(n.id, []);
  for (const e of graph.edges) incoming.get(e.target)?.push(e.source);

  const depthCache = new Map<string, number>();
  const depthOf = (id: string, stack: Set<string>): number => {
    const cached = depthCache.get(id);
    if (cached !== undefined) return cached;
    let d = 0;
    for (const up of incoming.get(id) ?? []) {
      if (stack.has(up)) continue; // guard against accidental cycles
      d = Math.max(d, depthOf(up, new Set(stack).add(id)) + 1);
    }
    depthCache.set(id, d);
    return d;
  };

  const byDepth = new Map<number, string[]>();
  for (const n of graph.nodes) {
    const d = depthOf(n.id, new Set([n.id]));
    if (!byDepth.has(d)) byDepth.set(d, []);
    byDepth.get(d)!.push(n.id);
  }

  const pos = new Map<string, { x: number; y: number }>();
  for (const [d, ids] of byDepth) {
    ids.forEach((id, i) => pos.set(id, { x: d * COL_GAP, y: i * ROW_GAP }));
  }
  return pos;
}

function buildOption(graph: LineageGraph, theme: ReturnType<typeof readChartTheme>): EChartsOption {
  const pos = layout(graph);
  const labelMap = Object.fromEntries(graph.nodes.map((n) => [n.id, n.label]));
  return {
    tooltip: {
      trigger: "item",
      backgroundColor: theme.tooltipBg,
      borderColor: theme.tooltipBorder,
      textStyle: { color: theme.text },
    },
    series: [
      {
        type: "graph",
        layout: "none",
        roam: true,
        symbol: "roundRect",
        symbolSize: 14,
        edgeSymbol: ["none", "arrow"],
        edgeSymbolSize: 7,
        lineStyle: { color: theme.axisLine, opacity: 0.8, curveness: 0.05 },
        label: {
          show: true,
          position: "right",
          color: theme.text,
          fontSize: 11,
          formatter: (p) => labelMap[(p.data as { name: string }).name] ?? "",
        },
        emphasis: { focus: "adjacency" },
        data: graph.nodes.map((n) => {
          const p = pos.get(n.id) ?? { x: 0, y: 0 };
          return {
            name: n.id,
            x: p.x,
            y: p.y,
            itemStyle: { color: colorForKind(n.kind, theme.palette) },
            tooltip: { formatter: `${n.label} · ${n.kind}${n.layer ? ` · ${n.layer}` : ""}` },
          };
        }),
        links: graph.edges.map((e) => ({ source: e.source, target: e.target })),
      },
    ],
  };
}

const LEGEND: { kind: string; label: string }[] = [
  { kind: "model", label: "Model" },
  { kind: "source", label: "Source" },
  { kind: "external", label: "External ref" },
];

export function LineageView() {
  const { data: graph, isLoading, isError, error } = useDbtLineage();
  const { resolvedTheme } = useTheme();
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  const hasGraph = !!graph && graph.nodes.length > 0;

  // Init the chart instance once the container is shown and there's a graph.
  useEffect(() => {
    if (!hasGraph || !containerRef.current) return;
    const instance = echarts.init(containerRef.current);
    chartRef.current = instance;
    const observer = new ResizeObserver(() => instance.resize());
    observer.observe(containerRef.current);
    return () => {
      observer.disconnect();
      instance.dispose();
      chartRef.current = null;
    };
  }, [hasGraph]);

  // (Re)set the option when the graph or theme changes.
  useEffect(() => {
    if (!hasGraph || !chartRef.current || !graph) return;
    chartRef.current.setOption(buildOption(graph, readChartTheme()), true);
  }, [graph, hasGraph, resolvedTheme]);

  const palette = useMemo(() => readChartTheme().palette, []);

  if (isLoading) {
    return (
      <div className="flex h-72 items-center justify-center">
        <Spinner label="Building lineage" />
      </div>
    );
  }
  if (isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Couldn't load lineage</AlertTitle>
        <AlertDescription>
          {error instanceof Error ? error.message : "The lineage graph could not be built."}
        </AlertDescription>
      </Alert>
    );
  }
  if (!hasGraph) {
    return (
      <EmptyState
        icon={<Network className="h-6 w-6" />}
        title="No lineage yet"
        description="Define dbt models that reference each other (or a source) to see the dependency graph."
      />
    );
  }

  return (
    <div className="rounded-xl border bg-card/70 p-4">
      <div className="mb-3 flex flex-wrap items-center gap-4">
        {LEGEND.map((l) => (
          <span key={l.kind} className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <span
              className="inline-block h-3 w-3 rounded-sm"
              style={{ backgroundColor: colorForKind(l.kind, palette) }}
            />
            {l.label}
          </span>
        ))}
        <span className="ml-auto text-xs text-muted-foreground">Scroll to zoom · drag to pan</span>
      </div>
      <div
        ref={containerRef}
        role="img"
        aria-label="dbt lineage graph"
        className="h-[28rem] w-full"
      />
    </div>
  );
}
