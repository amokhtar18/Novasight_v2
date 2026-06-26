// frontend/src/components/dashboard/filterControls/NumericFilterControl.tsx
import { Input } from "@/components/ui/input";

interface Props {
  min: number | null;
  max: number | null;
  onChange: (next: { min: number | null; max: number | null }) => void;
  label: string;
}

const parse = (s: string): number | null => (s.trim() === "" ? null : Number(s));

export function NumericFilterControl({ min, max, onChange, label }: Props) {
  return (
    <div className="flex gap-1">
      <Input type="number" value={min ?? ""} onChange={(e) => onChange({ min: parse(e.target.value), max })} placeholder="min" aria-label={`${label} min`} className="h-8" />
      <Input type="number" value={max ?? ""} onChange={(e) => onChange({ min, max: parse(e.target.value) })} placeholder="max" aria-label={`${label} max`} className="h-8" />
    </div>
  );
}
