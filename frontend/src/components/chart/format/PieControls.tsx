/**
 * PieControls — per-family format panel for pie/donut charts.
 *
 * Edits `options.type_options.pie` via the immutable setFamily helper.
 * Covers: label_type/inner_radius/outer_radius/rose_type/labels_outside/
 * label_line/show_total/show_labels_threshold/group_others_threshold.
 */

import type { ChartOptions, PieOptions } from "@/types/api";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { humanize } from "@/lib/format";
import { setFamily } from "./helpers";

const LABEL_TYPES: NonNullable<PieOptions["label_type"]>[] = [
  "category",
  "value",
  "percent",
  "category_value",
  "value_percent",
  "category_value_percent",
];

const ROSE_TYPES: NonNullable<PieOptions["rose_type"]>[] = ["none", "area", "radius"];

interface Props {
  options: ChartOptions;
  setOptions: (o: ChartOptions) => void;
}

export function PieControls({ options, setOptions }: Props) {
  const po: PieOptions = options.type_options?.pie ?? {};

  const set = (patch: Partial<PieOptions>) =>
    setOptions(setFamily(options, "pie", patch));

  const numOrNull = (s: string): number | null =>
    s.trim() !== "" && Number.isFinite(Number(s)) ? Number(s) : null;

  return (
    <details className="rounded-lg border bg-background/40 p-3">
      <summary className="cursor-pointer text-sm font-medium">Pie / donut options</summary>
      <div className="mt-3 space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="pc-label-type">Label type</Label>
            <Select
              id="pc-label-type"
              value={po.label_type ?? "category"}
              onChange={(e) => set({ label_type: e.target.value as PieOptions["label_type"] })}
            >
              {LABEL_TYPES.map((t) => (
                <option key={t} value={t}>
                  {humanize(t)}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="pc-rose-type">Rose type</Label>
            <Select
              id="pc-rose-type"
              value={po.rose_type ?? "none"}
              onChange={(e) => set({ rose_type: e.target.value as PieOptions["rose_type"] })}
            >
              {ROSE_TYPES.map((r) => (
                <option key={r} value={r}>
                  {humanize(r)}
                </option>
              ))}
            </Select>
          </div>
        </div>

        {/* Radii */}
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="pc-inner-radius">Inner radius (%)</Label>
            <Input
              id="pc-inner-radius"
              value={po.inner_radius != null ? String(po.inner_radius) : ""}
              onChange={(e) => set({ inner_radius: numOrNull(e.target.value) })}
              placeholder="0 = pie, 50 = donut"
              inputMode="numeric"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="pc-outer-radius">Outer radius (%)</Label>
            <Input
              id="pc-outer-radius"
              value={po.outer_radius != null ? String(po.outer_radius) : ""}
              onChange={(e) => set({ outer_radius: numOrNull(e.target.value) })}
              placeholder="75"
              inputMode="numeric"
            />
          </div>
        </div>

        {/* Thresholds */}
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="pc-show-labels-threshold">Show labels threshold</Label>
            <Input
              id="pc-show-labels-threshold"
              value={po.show_labels_threshold != null ? String(po.show_labels_threshold) : ""}
              onChange={(e) => set({ show_labels_threshold: numOrNull(e.target.value) })}
              placeholder="min % to show label"
              inputMode="decimal"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="pc-group-others">Group others threshold</Label>
            <Input
              id="pc-group-others-threshold"
              value={po.group_others_threshold != null ? String(po.group_others_threshold) : ""}
              onChange={(e) => set({ group_others_threshold: numOrNull(e.target.value) })}
              placeholder="min % before grouping"
              inputMode="decimal"
            />
          </div>
        </div>

        {/* Checkboxes */}
        <div className="flex flex-wrap gap-x-4 gap-y-2 text-sm">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={po.labels_outside ?? false}
              onChange={(e) => set({ labels_outside: e.target.checked })}
            />
            Labels outside
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={po.label_line ?? false}
              onChange={(e) => set({ label_line: e.target.checked })}
            />
            Label line
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={po.show_total ?? false}
              onChange={(e) => set({ show_total: e.target.checked })}
            />
            Show total
          </label>
        </div>
      </div>
    </details>
  );
}
