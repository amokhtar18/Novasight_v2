// frontend/src/components/dashboard/filterControls/TimeFilterControl.tsx
import { Select } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import type { RelativeDateRange } from "@/types/api";

const PRESETS: RelativeDateRange[] = [
  "last_7_days", "last_30_days", "last_90_days", "this_month", "last_month",
  "this_quarter", "last_quarter", "this_year", "last_year",
];

interface Props {
  value: RelativeDateRange | string[] | null;
  onChange: (next: RelativeDateRange | string[] | null) => void;
  label: string;
}

export function TimeFilterControl({ value, onChange, label }: Props) {
  const isCustom = Array.isArray(value);
  const mode = value === null ? "none" : isCustom ? "custom" : "preset";
  const [from, to] = Array.isArray(value) ? value : ["", ""];

  return (
    <div className="space-y-1.5">
      <Select
        aria-label={`${label} range`}
        value={mode === "preset" ? (value as string) : mode}
        onChange={(e) => {
          const v = e.target.value;
          if (v === "none") onChange(null);
          else if (v === "custom") onChange(["", ""]);
          else onChange(v as RelativeDateRange);
        }}
        className="h-8"
      >
        <option value="none">No filter</option>
        {PRESETS.map((p) => (
          <option key={p} value={p}>{p.replace(/_/g, " ")}</option>
        ))}
        <option value="custom">Custom…</option>
      </Select>
      {isCustom && (
        <div className="flex gap-1">
          <Input type="date" value={from} onChange={(e) => onChange([e.target.value, to])} aria-label={`${label} from`} className="h-8" />
          <Input type="date" value={to} onChange={(e) => onChange([from, e.target.value])} aria-label={`${label} to`} className="h-8" />
        </div>
      )}
    </div>
  );
}
