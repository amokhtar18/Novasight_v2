/**
 * DashboardFilterBar — horizontal top bar of native filters (command-center layout).
 * One control per filter (value/time/numeric); reuses the same controls + cascading
 * the left drawer used, laid out inline. In edit mode it exposes Add/Edit.
 */
import { Filter, Pencil, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { ValueFilterControl } from "./filterControls/ValueFilterControl";
import { TimeFilterControl } from "./filterControls/TimeFilterControl";
import { NumericFilterControl } from "./filterControls/NumericFilterControl";
import { defaultSelection } from "@/lib/dashboardFilters";
import type { FilterSelection, FilterSelections } from "@/lib/dashboardFilters";
import type { NativeFilter, SemanticFilter } from "@/types/api";

interface Props {
  filters: NativeFilter[];
  selections: FilterSelections;
  onSelectionChange: (id: string, sel: FilterSelection) => void;
  onClearAll: () => void;
  editing: boolean;
  onAddFilter?: () => void;
  onEditFilter?: (id: string) => void;
}

/** Parent selection of a value filter expressed as a constraint for cascading. */
function parentConstraints(filter: NativeFilter, all: NativeFilter[], selections: FilterSelections): SemanticFilter[] {
  if (!filter.parent_id) return [];
  const parent = all.find((f) => f.id === filter.parent_id);
  if (!parent) return [];
  const sel = selections[parent.id] ?? defaultSelection(parent);
  if (sel.kind === "value" && sel.values.length > 0) {
    return [{ member: parent.member, operator: parent.operator ?? "equals", values: sel.values }];
  }
  return [];
}

export function DashboardFilterBar({
  filters, selections, onSelectionChange, onClearAll, editing, onAddFilter, onEditFilter,
}: Props) {
  if (filters.length === 0 && !editing) return null;

  return (
    <div className="mb-4 flex flex-wrap items-end gap-3 rounded-xl border bg-card/40 p-3 shadow-[var(--elevation-1)]">
      <span className="flex h-9 items-center gap-1.5 text-sm font-medium">
        <Filter className="h-4 w-4" aria-hidden /> Filters
      </span>

      {filters.map((f) => {
        const sel = selections[f.id] ?? defaultSelection(f);
        return (
          <div key={f.id} className="flex min-w-[10rem] flex-col gap-1">
            <div className="flex items-center justify-between">
              <Label className="text-xs text-muted-foreground">
                {f.label ?? f.member}{f.required ? " *" : ""}
              </Label>
              {editing && onEditFilter && (
                <button type="button" aria-label={`Edit ${f.label ?? f.member}`} onClick={() => onEditFilter(f.id)} className="text-muted-foreground hover:text-foreground">
                  <Pencil className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
            {f.kind === "value" && sel.kind === "value" && (
              <ValueFilterControl
                filter={f}
                values={sel.values}
                onChange={(values) => onSelectionChange(f.id, { kind: "value", values })}
                constraints={parentConstraints(f, filters, selections)}
                enabled={!editing}
              />
            )}
            {f.kind === "time" && sel.kind === "time" && (
              <TimeFilterControl
                value={sel.date_range}
                onChange={(date_range) => onSelectionChange(f.id, { kind: "time", date_range })}
                label={f.label ?? f.member}
              />
            )}
            {f.kind === "numeric" && sel.kind === "numeric" && (
              <NumericFilterControl
                min={sel.min}
                max={sel.max}
                onChange={({ min, max }) => onSelectionChange(f.id, { kind: "numeric", min, max })}
                label={f.label ?? f.member}
              />
            )}
            {f.required && sel.kind === "value" && sel.values.length === 0 && (
              <p className="text-xs text-amber-600">A selection is required.</p>
            )}
          </div>
        );
      })}

      <div className="ml-auto flex items-center gap-2">
        {filters.length > 0 && (
          <Button variant="ghost" size="sm" onClick={onClearAll}>Clear all</Button>
        )}
        {editing && onAddFilter && (
          <Button variant="outline" size="sm" onClick={onAddFilter}>
            <Plus className="h-4 w-4" aria-hidden /> Add filter
          </Button>
        )}
      </div>
    </div>
  );
}
