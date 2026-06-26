/**
 * FormatControls — type-aware chart formatting panel (Task 10, Slice A2).
 *
 * Renders the shared chrome (SharedFormatControls) for every chart type,
 * then dispatches to the correct per-family panel via FAMILY_FOR_TYPE.
 *
 * Exported interface consumed by Task 11 (Builder wire-up):
 *   FormatControls({ options, setOptions, chartType })
 *   FAMILY_FOR_TYPE: Record<ChartType, Family | null>
 */

import type { ChartOptions, ChartType } from "@/types/api";
import { SharedFormatControls } from "./SharedFormatControls";
import { CartesianControls } from "./CartesianControls";
import { PieControls } from "./PieControls";
import { GaugeControls } from "./GaugeControls";
import { FunnelControls } from "./FunnelControls";
import { RadarControls } from "./RadarControls";
import { TreemapControls } from "./TreemapControls";
import { NumberControls } from "./NumberControls";

/** The chart-family discriminant — null for types that have no per-family panel. */
export type Family =
  | "cartesian"
  | "pie"
  | "gauge"
  | "funnel"
  | "radar"
  | "treemap"
  | "number";

/**
 * Maps every ChartType to its Family (or null for `table`).
 * Task 11 and consumers may import this map directly.
 */
export const FAMILY_FOR_TYPE: Record<ChartType, Family | null> = {
  bar: "cartesian",
  hbar: "cartesian",
  line: "cartesian",
  area: "cartesian",
  combo: "cartesian",
  scatter: "cartesian",
  pie: "pie",
  donut: "pie",
  gauge: "gauge",
  funnel: "funnel",
  radar: "radar",
  treemap: "treemap",
  heatmap: null,
  sankey: null,
  number: "number",
  table: null,
};

export interface FormatControlsProps {
  options: ChartOptions;
  setOptions: (o: ChartOptions) => void;
  chartType: ChartType;
}

/**
 * FormatControls — the full format side-panel.
 *
 * Always renders SharedFormatControls (title, legend, number format, labels,
 * tooltip, sort), then appends the per-family panel when the chart type has one.
 */
export function FormatControls({ options, setOptions, chartType }: FormatControlsProps) {
  const family = FAMILY_FOR_TYPE[chartType];

  return (
    <div className="space-y-2">
      <SharedFormatControls options={options} setOptions={setOptions} />

      {family === "cartesian" && (
        <CartesianControls options={options} setOptions={setOptions} />
      )}
      {family === "pie" && (
        <PieControls options={options} setOptions={setOptions} />
      )}
      {family === "gauge" && (
        <GaugeControls options={options} setOptions={setOptions} />
      )}
      {family === "funnel" && (
        <FunnelControls options={options} setOptions={setOptions} />
      )}
      {family === "radar" && (
        <RadarControls options={options} setOptions={setOptions} />
      )}
      {family === "treemap" && (
        <TreemapControls options={options} setOptions={setOptions} />
      )}
      {family === "number" && (
        <NumberControls options={options} setOptions={setOptions} />
      )}
    </div>
  );
}
