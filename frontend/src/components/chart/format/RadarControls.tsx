/**
 * RadarControls — per-family format panel for radar charts.
 *
 * Edits `options.type_options.radar` via the immutable setFamily helper.
 * Covers: shape/label_type/label_position.
 * (metric_bounds is a dynamic Record<string, MetricBound> — omitted from the
 * generic panel; callers may extend this if per-metric bounds UI is needed.)
 */

import type { ChartOptions, RadarOptions } from "@/types/api";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { humanize } from "@/lib/format";
import { setFamily } from "./helpers";

const SHAPES: NonNullable<RadarOptions["shape"]>[] = ["polygon", "circle"];
const LABEL_TYPES: NonNullable<RadarOptions["label_type"]>[] = ["value", "category_value"];

interface Props {
  options: ChartOptions;
  setOptions: (o: ChartOptions) => void;
}

export function RadarControls({ options, setOptions }: Props) {
  const ro: RadarOptions = options.type_options?.radar ?? {};

  const set = (patch: Partial<RadarOptions>) =>
    setOptions(setFamily(options, "radar", patch));

  return (
    <details className="rounded-lg border bg-background/40 p-3">
      <summary className="cursor-pointer text-sm font-medium">Radar options</summary>
      <div className="mt-3 space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="rc-shape">Shape</Label>
            <Select
              id="rc-shape"
              value={ro.shape ?? "polygon"}
              onChange={(e) => set({ shape: e.target.value as RadarOptions["shape"] })}
            >
              {SHAPES.map((s) => (
                <option key={s} value={s}>
                  {humanize(s)}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="rc-label-type">Label type</Label>
            <Select
              id="rc-label-type"
              value={ro.label_type ?? "value"}
              onChange={(e) => set({ label_type: e.target.value as RadarOptions["label_type"] })}
            >
              {LABEL_TYPES.map((t) => (
                <option key={t} value={t}>
                  {humanize(t)}
                </option>
              ))}
            </Select>
          </div>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="rc-label-position">Label position</Label>
          <Input
            id="rc-label-position"
            value={ro.label_position ?? ""}
            onChange={(e) => set({ label_position: e.target.value || null })}
            placeholder="e.g. top"
          />
        </div>
      </div>
    </details>
  );
}
