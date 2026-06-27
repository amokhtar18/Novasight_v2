/**
 * CartesianControls — per-family format panel for bar/line/area/hbar/combo/scatter.
 *
 * Edits `options.type_options.cartesian` via the immutable setFamily helper.
 * Covers: stacked/percent/only_total/area_opacity/markers/marker_size/smooth/
 * x_label_rotation/x_label_interval/y_min/y_max/log_scale/minor_ticks/
 * minor_split_line/data_zoom/sort_series/x_axis_label/y_axis_label.
 */

import type { ChartOptions, CartesianOptions } from "@/types/api";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Checkbox } from "@/components/ui/checkbox";
import { humanize } from "@/lib/format";
import { setFamily } from "./helpers";

const SORT_SERIES_OPTIONS = ["none", "asc", "desc"] as const;
const X_LABEL_ROTATIONS = ["0", "45", "90"] as const;
const X_LABEL_INTERVALS = ["auto", "all"] as const;

interface Props {
  options: ChartOptions;
  setOptions: (o: ChartOptions) => void;
}

export function CartesianControls({ options, setOptions }: Props) {
  const co: CartesianOptions = options.type_options?.cartesian ?? {};

  const set = (patch: Partial<CartesianOptions>) =>
    setOptions(setFamily(options, "cartesian", patch));

  const numOrNull = (s: string): number | null =>
    s.trim() !== "" && Number.isFinite(Number(s)) ? Number(s) : null;

  return (
    <details className="rounded-lg border bg-background/40 p-3">
      <summary className="cursor-pointer text-sm font-medium">Cartesian axis options</summary>
      <div className="mt-3 space-y-3">
        {/* Axis labels */}
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="cc-x-axis-label">X axis label</Label>
            <Input
              id="cc-x-axis-label"
              value={co.x_axis_label ?? ""}
              onChange={(e) => set({ x_axis_label: e.target.value || null })}
              placeholder="auto"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="cc-y-axis-label">Y axis label</Label>
            <Input
              id="cc-y-axis-label"
              value={co.y_axis_label ?? ""}
              onChange={(e) => set({ y_axis_label: e.target.value || null })}
              placeholder="auto"
            />
          </div>
        </div>

        {/* Y range */}
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="cc-y-min">Y min</Label>
            <Input
              id="cc-y-min"
              value={co.y_min != null ? String(co.y_min) : ""}
              onChange={(e) => set({ y_min: numOrNull(e.target.value) })}
              placeholder="auto"
              inputMode="numeric"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="cc-y-max">Y max</Label>
            <Input
              id="cc-y-max"
              value={co.y_max != null ? String(co.y_max) : ""}
              onChange={(e) => set({ y_max: numOrNull(e.target.value) })}
              placeholder="auto"
              inputMode="numeric"
            />
          </div>
        </div>

        {/* X label rotation + interval */}
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="cc-x-rotation">X label rotation</Label>
            <Select
              id="cc-x-rotation"
              value={co.x_label_rotation != null ? String(co.x_label_rotation) : "0"}
              onChange={(e) =>
                set({
                  x_label_rotation: (Number(e.target.value) as CartesianOptions["x_label_rotation"]) ?? null,
                })
              }
            >
              {X_LABEL_ROTATIONS.map((r) => (
                <option key={r} value={r}>
                  {r}°
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="cc-x-interval">X label interval</Label>
            <Select
              id="cc-x-interval"
              value={co.x_label_interval ?? "auto"}
              onChange={(e) =>
                set({ x_label_interval: e.target.value as CartesianOptions["x_label_interval"] })
              }
            >
              {X_LABEL_INTERVALS.map((i) => (
                <option key={i} value={i}>
                  {humanize(i)}
                </option>
              ))}
            </Select>
          </div>
        </div>

        {/* Area opacity + marker size */}
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="cc-area-opacity">Area opacity (0–1)</Label>
            <Input
              id="cc-area-opacity"
              value={co.area_opacity != null ? String(co.area_opacity) : ""}
              onChange={(e) => set({ area_opacity: numOrNull(e.target.value) })}
              placeholder="0.2"
              inputMode="decimal"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="cc-marker-size">Marker size (px)</Label>
            <Input
              id="cc-marker-size"
              value={co.marker_size != null ? String(co.marker_size) : ""}
              onChange={(e) => set({ marker_size: numOrNull(e.target.value) })}
              placeholder="4"
              inputMode="numeric"
            />
          </div>
        </div>

        {/* Sort series */}
        <div className="space-y-1.5">
          <Label htmlFor="cc-sort-series">Sort series</Label>
          <Select
            id="cc-sort-series"
            value={co.sort_series ?? "none"}
            onChange={(e) =>
              set({ sort_series: e.target.value as CartesianOptions["sort_series"] })
            }
          >
            {SORT_SERIES_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {humanize(s)}
              </option>
            ))}
          </Select>
        </div>

        {/* Checkboxes */}
        <div className="flex flex-wrap gap-x-4 gap-y-2 text-sm">
          <label className="flex items-center gap-2">
            <Checkbox
              checked={co.stacked ?? false}
              onChange={(e) => set({ stacked: e.target.checked })}
            />
            Stacked
          </label>
          <label className="flex items-center gap-2">
            <Checkbox
              checked={co.percent ?? false}
              onChange={(e) => set({ percent: e.target.checked })}
            />
            Percent
          </label>
          <label className="flex items-center gap-2">
            <Checkbox
              checked={co.only_total ?? false}
              onChange={(e) => set({ only_total: e.target.checked })}
            />
            Only total
          </label>
          <label className="flex items-center gap-2">
            <Checkbox
              checked={co.markers ?? false}
              onChange={(e) => set({ markers: e.target.checked })}
            />
            Markers
          </label>
          <label className="flex items-center gap-2">
            <Checkbox
              checked={co.smooth ?? false}
              onChange={(e) => set({ smooth: e.target.checked })}
            />
            Smooth
          </label>
          <label className="flex items-center gap-2">
            <Checkbox
              checked={co.log_scale ?? false}
              onChange={(e) => set({ log_scale: e.target.checked })}
            />
            Log scale
          </label>
          <label className="flex items-center gap-2">
            <Checkbox
              checked={co.minor_ticks ?? false}
              onChange={(e) => set({ minor_ticks: e.target.checked })}
            />
            Minor ticks
          </label>
          <label className="flex items-center gap-2">
            <Checkbox
              checked={co.minor_split_line ?? false}
              onChange={(e) => set({ minor_split_line: e.target.checked })}
            />
            Minor split line
          </label>
          <label className="flex items-center gap-2">
            <Checkbox
              checked={co.data_zoom ?? false}
              onChange={(e) => set({ data_zoom: e.target.checked })}
            />
            Data zoom
          </label>
        </div>
      </div>
    </details>
  );
}
