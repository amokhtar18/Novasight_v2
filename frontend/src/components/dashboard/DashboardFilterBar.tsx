/**
 * DashboardFilterBar — a view-time filter applied across a dashboard's tiles.
 *
 * Pick a governed dimension and a value; the active filter is handed up to the
 * dashboard, which passes it to each tile. A tile applies it only when it is a
 * semantic chart on the same cube (see DashboardCardTile), so a filter never breaks
 * an unrelated tile. The dimension options come from the tenant's governed semantic
 * models, so the bar can only offer fields the server will accept (it re-validates).
 *
 * A single filter on one member; values is one entry. Multi-value and dataset-tile
 * filtering are later slices. The filter is persisted by the dashboard.
 */

import { useMemo } from "react";
import { Filter, X } from "lucide-react";

import { useSemanticModels } from "@/api/hooks";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import type { SemanticFilter, SemanticFilterOperator } from "@/types/api";

interface DashboardFilterBarProps {
  value: SemanticFilter | null;
  onChange: (filter: SemanticFilter | null) => void;
  /**
   * The cubes present on the dashboard's tiles. When provided, only dimensions on
   * those cubes are offered — a filter on a cube no tile uses would affect nothing.
   * Omitted → offer every governed dimension.
   */
  cubes?: ReadonlySet<string>;
}

/** The cube a fully-qualified member belongs to (the part before the first dot). */
function cubeOf(member: string): string | undefined {
  return member.includes(".") ? member.split(".")[0] : undefined;
}

// Operators offered, with friendly labels. `set`/`notSet` are presence checks that
// take no value (mirrors the closed set the API accepts).
const OPERATORS: { value: SemanticFilterOperator; label: string }[] = [
  { value: "equals", label: "equals" },
  { value: "notEquals", label: "not equals" },
  { value: "contains", label: "contains" },
  { value: "notContains", label: "not contains" },
  { value: "gt", label: ">" },
  { value: "gte", label: "≥" },
  { value: "lt", label: "<" },
  { value: "lte", label: "≤" },
  { value: "set", label: "is set" },
  { value: "notSet", label: "is not set" },
];

const VALUELESS: ReadonlySet<SemanticFilterOperator> = new Set(["set", "notSet"]);

export function DashboardFilterBar({ value, onChange, cubes }: DashboardFilterBarProps) {
  const { data: models } = useSemanticModels();

  // Flatten governed dimensions into a pick list, labelled by their model. When the
  // dashboard's cubes are known, keep only dimensions on a cube some tile uses.
  const options = useMemo(
    () =>
      (models ?? [])
        .flatMap((m) =>
          m.dimensions.map((d) => ({ value: d.name, label: `${m.title} · ${d.title}` }))
        )
        .filter((o) => {
          if (!cubes) return true;
          const cube = cubeOf(o.value);
          return cube !== undefined && cubes.has(cube);
        }),
    [models, cubes]
  );

  const member = value?.member ?? "";
  const operator: SemanticFilterOperator = value?.operator ?? "equals";
  const text = value?.values[0] ?? "";

  function emit(
    nextMember: string,
    nextOperator: SemanticFilterOperator,
    nextText: string
  ) {
    if (!nextMember) {
      onChange(null);
    } else if (VALUELESS.has(nextOperator)) {
      // Presence checks need no value — active as soon as a member is chosen.
      onChange({ member: nextMember, operator: nextOperator, values: [] });
    } else if (nextText.trim()) {
      onChange({ member: nextMember, operator: nextOperator, values: [nextText.trim()] });
    } else {
      onChange(null);
    }
  }

  // Nothing to filter on (no governed dimensions) → don't render the bar.
  if (options.length === 0) return null;

  const valueless = VALUELESS.has(operator);

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
          onChange={(e) => emit(e.target.value, operator, text)}
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
        <Label htmlFor="dash-filter-op" className="text-xs text-muted-foreground">
          Operator
        </Label>
        <Select
          id="dash-filter-op"
          value={operator}
          onChange={(e) => emit(member, e.target.value as SemanticFilterOperator, text)}
          disabled={!member}
          className="w-36"
        >
          {OPERATORS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </Select>
      </div>
      <div className="space-y-1">
        <Label htmlFor="dash-filter-val" className="text-xs text-muted-foreground">
          Value
        </Label>
        <Input
          id="dash-filter-val"
          value={valueless ? "" : text}
          onChange={(e) => emit(member, operator, e.target.value)}
          placeholder={valueless ? "—" : "value"}
          disabled={!member || valueless}
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
