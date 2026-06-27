/**
 * FunnelControls — per-family format panel for funnel charts.
 *
 * Edits `options.type_options.funnel` via the immutable setFamily helper.
 * Covers: label_type/tooltip_label_type/show_labels/show_tooltip_labels.
 */

import type { ChartOptions, FunnelOptions } from "@/types/api";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Checkbox } from "@/components/ui/checkbox";
import { humanize } from "@/lib/format";
import { setFamily } from "./helpers";

const LABEL_TYPES: NonNullable<FunnelOptions["label_type"]>[] = [
  "none",
  "value",
  "percent",
  "category",
  "category_value",
  "value_percent",
  "all",
];

const TOOLTIP_LABEL_TYPES: NonNullable<FunnelOptions["tooltip_label_type"]>[] = [
  "value",
  "percent",
  "category",
  "category_value",
  "value_percent",
  "all",
];

interface Props {
  options: ChartOptions;
  setOptions: (o: ChartOptions) => void;
}

export function FunnelControls({ options, setOptions }: Props) {
  const fo: FunnelOptions = options.type_options?.funnel ?? {};

  const set = (patch: Partial<FunnelOptions>) =>
    setOptions(setFamily(options, "funnel", patch));

  return (
    <details className="rounded-lg border bg-background/40 p-3">
      <summary className="cursor-pointer text-sm font-medium">Funnel options</summary>
      <div className="mt-3 space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="fc-label-type">Label type</Label>
            <Select
              id="fc-label-type"
              value={fo.label_type ?? "value"}
              onChange={(e) => set({ label_type: e.target.value as FunnelOptions["label_type"] })}
            >
              {LABEL_TYPES.map((t) => (
                <option key={t} value={t}>
                  {humanize(t)}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="fc-tooltip-label-type">Tooltip label type</Label>
            <Select
              id="fc-tooltip-label-type"
              value={fo.tooltip_label_type ?? "value"}
              onChange={(e) =>
                set({ tooltip_label_type: e.target.value as FunnelOptions["tooltip_label_type"] })
              }
            >
              {TOOLTIP_LABEL_TYPES.map((t) => (
                <option key={t} value={t}>
                  {humanize(t)}
                </option>
              ))}
            </Select>
          </div>
        </div>

        <div className="flex flex-wrap gap-x-4 gap-y-2 text-sm">
          <label className="flex items-center gap-2">
            <Checkbox
              checked={fo.show_labels ?? true}
              onChange={(e) => set({ show_labels: e.target.checked })}
            />
            Show labels
          </label>
          <label className="flex items-center gap-2">
            <Checkbox
              checked={fo.show_tooltip_labels ?? true}
              onChange={(e) => set({ show_tooltip_labels: e.target.checked })}
            />
            Show tooltip labels
          </label>
        </div>
      </div>
    </details>
  );
}
