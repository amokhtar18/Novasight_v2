/**
 * TreemapControls — per-family format panel for treemap charts.
 *
 * Edits `options.type_options.treemap` via the immutable setFamily helper.
 * Covers: show_labels/show_upper_labels/label_type.
 */

import type { ChartOptions, TreemapOptions } from "@/types/api";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { humanize } from "@/lib/format";
import { setFamily } from "./helpers";

const LABEL_TYPES: NonNullable<TreemapOptions["label_type"]>[] = [
  "key",
  "value",
  "key_value",
];

interface Props {
  options: ChartOptions;
  setOptions: (o: ChartOptions) => void;
}

export function TreemapControls({ options, setOptions }: Props) {
  const to: TreemapOptions = options.type_options?.treemap ?? {};

  const set = (patch: Partial<TreemapOptions>) =>
    setOptions(setFamily(options, "treemap", patch));

  return (
    <details className="rounded-lg border bg-background/40 p-3">
      <summary className="cursor-pointer text-sm font-medium">Treemap options</summary>
      <div className="mt-3 space-y-3">
        <div className="space-y-1.5">
          <Label htmlFor="tc-label-type">Label type</Label>
          <Select
            id="tc-label-type"
            value={to.label_type ?? "key"}
            onChange={(e) => set({ label_type: e.target.value as TreemapOptions["label_type"] })}
          >
            {LABEL_TYPES.map((t) => (
              <option key={t} value={t}>
                {humanize(t)}
              </option>
            ))}
          </Select>
        </div>

        <div className="flex flex-wrap gap-x-4 gap-y-2 text-sm">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={to.show_labels ?? true}
              onChange={(e) => set({ show_labels: e.target.checked })}
            />
            Show labels
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={to.show_upper_labels ?? false}
              onChange={(e) => set({ show_upper_labels: e.target.checked })}
            />
            Show upper labels
          </label>
        </div>
      </div>
    </details>
  );
}
