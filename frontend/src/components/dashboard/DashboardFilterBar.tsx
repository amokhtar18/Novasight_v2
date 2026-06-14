/**
 * DashboardFilterBar — a view-time filter applied across a dashboard's tiles.
 *
 * Pick a governed dimension and a value; the active filter is handed up to the
 * dashboard, which passes it to each tile. A tile applies it only when it is a
 * semantic chart on the same cube (see DashboardCardTile), so a filter never breaks
 * an unrelated tile. The dimension options come from the tenant's governed semantic
 * models, so the bar can only offer fields the server will accept (it re-validates).
 *
 * This is intentionally a single equals filter for now; multi-value/operators are a
 * later slice. Nothing is persisted yet — the filter lives in page state.
 */

import { useMemo } from "react";
import { Filter, X } from "lucide-react";

import { useSemanticModels } from "@/api/hooks";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import type { SemanticFilter } from "@/types/api";

interface DashboardFilterBarProps {
  value: SemanticFilter | null;
  onChange: (filter: SemanticFilter | null) => void;
}

export function DashboardFilterBar({ value, onChange }: DashboardFilterBarProps) {
  const { data: models } = useSemanticModels();

  // Flatten every governed dimension into a pick list, labelled by its model.
  const options = useMemo(
    () =>
      (models ?? []).flatMap((m) =>
        m.dimensions.map((d) => ({ value: d.name, label: `${m.title} · ${d.title}` }))
      ),
    [models]
  );

  const member = value?.member ?? "";
  const text = value?.values[0] ?? "";

  function apply(nextMember: string, nextText: string) {
    if (nextMember && nextText.trim()) {
      onChange({ member: nextMember, operator: "equals", values: [nextText.trim()] });
    } else {
      onChange(null);
    }
  }

  // Nothing to filter on (no governed dimensions) → don't render the bar.
  if (options.length === 0) return null;

  return (
    <div className="mb-4 flex flex-wrap items-end gap-3 rounded-lg border bg-card/50 p-3">
      <div className="flex items-center gap-1.5 self-center text-sm text-muted-foreground">
        <Filter className="h-4 w-4" aria-hidden />
        Filter
      </div>
      <div className="space-y-1">
        <Label htmlFor="dash-filter-dim" className="text-xs text-muted-foreground">
          Dimension
        </Label>
        <Select
          id="dash-filter-dim"
          value={member}
          onChange={(e) => apply(e.target.value, text)}
          className="w-56"
        >
          <option value="">No filter</option>
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </Select>
      </div>
      <div className="space-y-1">
        <Label htmlFor="dash-filter-val" className="text-xs text-muted-foreground">
          Equals
        </Label>
        <Input
          id="dash-filter-val"
          value={text}
          onChange={(e) => apply(member, e.target.value)}
          placeholder="value"
          disabled={!member}
          className="w-48"
        />
      </div>
      {value && (
        <Button variant="ghost" size="sm" onClick={() => onChange(null)}>
          <X className="h-4 w-4" aria-hidden />
          Clear
        </Button>
      )}
    </div>
  );
}
