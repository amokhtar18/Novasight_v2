/**
 * GaugeControls — per-family format panel for gauge charts.
 *
 * Edits `options.type_options.gauge` via the immutable setFamily helper.
 * Covers: min/max/start_angle/end_angle/show_pointer/show_progress/round_cap/
 * show_axis_tick/show_split_line/split_number/font_size/animation.
 */

import type { ChartOptions, GaugeOptions } from "@/types/api";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { setFamily } from "./helpers";

interface Props {
  options: ChartOptions;
  setOptions: (o: ChartOptions) => void;
}

export function GaugeControls({ options, setOptions }: Props) {
  const go: GaugeOptions = options.type_options?.gauge ?? {};

  const set = (patch: Partial<GaugeOptions>) =>
    setOptions(setFamily(options, "gauge", patch));

  const numOrNull = (s: string): number | null =>
    s.trim() !== "" && Number.isFinite(Number(s)) ? Number(s) : null;

  return (
    <details className="rounded-lg border bg-background/40 p-3">
      <summary className="cursor-pointer text-sm font-medium">Gauge options</summary>
      <div className="mt-3 space-y-3">
        {/* Min / Max */}
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="gc-min">Min</Label>
            <Input
              id="gc-min"
              value={go.min != null ? String(go.min) : ""}
              onChange={(e) => set({ min: numOrNull(e.target.value) })}
              placeholder="0"
              inputMode="numeric"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="gc-max">Max</Label>
            <Input
              id="gc-max"
              value={go.max != null ? String(go.max) : ""}
              onChange={(e) => set({ max: numOrNull(e.target.value) })}
              placeholder="100"
              inputMode="numeric"
            />
          </div>
        </div>

        {/* Start / End angle */}
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="gc-start-angle">Start angle (°)</Label>
            <Input
              id="gc-start-angle"
              value={go.start_angle != null ? String(go.start_angle) : ""}
              onChange={(e) => set({ start_angle: numOrNull(e.target.value) })}
              placeholder="225"
              inputMode="numeric"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="gc-end-angle">End angle (°)</Label>
            <Input
              id="gc-end-angle"
              value={go.end_angle != null ? String(go.end_angle) : ""}
              onChange={(e) => set({ end_angle: numOrNull(e.target.value) })}
              placeholder="-45"
              inputMode="numeric"
            />
          </div>
        </div>

        {/* Split number + font size */}
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="gc-split-number">Split number</Label>
            <Input
              id="gc-split-number"
              value={go.split_number != null ? String(go.split_number) : ""}
              onChange={(e) => set({ split_number: numOrNull(e.target.value) })}
              placeholder="5"
              inputMode="numeric"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="gc-font-size">Font size (px)</Label>
            <Input
              id="gc-font-size"
              value={go.font_size != null ? String(go.font_size) : ""}
              onChange={(e) => set({ font_size: numOrNull(e.target.value) })}
              placeholder="auto"
              inputMode="numeric"
            />
          </div>
        </div>

        {/* Checkboxes */}
        <div className="flex flex-wrap gap-x-4 gap-y-2 text-sm">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={go.show_pointer ?? true}
              onChange={(e) => set({ show_pointer: e.target.checked })}
            />
            Show pointer
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={go.show_progress ?? false}
              onChange={(e) => set({ show_progress: e.target.checked })}
            />
            Show progress
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={go.round_cap ?? false}
              onChange={(e) => set({ round_cap: e.target.checked })}
            />
            Round cap
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={go.show_axis_tick ?? false}
              onChange={(e) => set({ show_axis_tick: e.target.checked })}
            />
            Show axis tick
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={go.show_split_line ?? false}
              onChange={(e) => set({ show_split_line: e.target.checked })}
            />
            Show split line
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={go.animation ?? true}
              onChange={(e) => set({ animation: e.target.checked })}
            />
            Animation
          </label>
        </div>
      </div>
    </details>
  );
}
