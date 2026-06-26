// frontend/src/components/dashboard/filterControls/ValueFilterControl.tsx
/**
 * ValueFilterControl — multi-select for a value native filter, fed by grounded
 * /semantic/values. `constraints` carry the parent selection for cascading.
 */
import { useEffect, useState } from "react";

import { useSemanticValues } from "@/api/hooks";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import type { NativeFilter, SemanticFilter } from "@/types/api";

interface Props {
  filter: NativeFilter;
  values: string[];
  onChange: (values: string[]) => void;
  constraints?: SemanticFilter[];
  enabled?: boolean;
}

export function ValueFilterControl({ filter, values, onChange, constraints, enabled = true }: Props) {
  const [search, setSearch] = useState("");
  // Debounce typeahead so each keystroke doesn't fire its own /semantic/values request.
  const [debouncedSearch, setDebouncedSearch] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 250);
    return () => clearTimeout(t);
  }, [search]);

  const { data } = useSemanticValues(
    enabled ? { member: filter.member, search: debouncedSearch || null, constraints } : null
  );
  const options = data?.values ?? [];

  const toggle = (v: string) =>
    onChange(values.includes(v) ? values.filter((x) => x !== v) : [...values, v]);

  return (
    <div className="space-y-1.5">
      <Input
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search…"
        aria-label={`Search ${filter.label ?? filter.member}`}
        className="h-8"
      />
      <div className="flex max-h-40 flex-col gap-1 overflow-auto">
        {options.map((o) => (
          <label key={o} className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={values.includes(o)} onChange={() => toggle(o)} />
            {o}
          </label>
        ))}
        {options.length === 0 && <span className="text-xs text-muted-foreground">No values</span>}
      </div>
      {values.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {values.map((v) => (
            <Badge
              key={v}
              variant="secondary"
              role="button"
              tabIndex={0}
              aria-label={`Remove ${v}`}
              className="cursor-pointer"
              onClick={() => toggle(v)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  toggle(v);
                }
              }}
            >
              {v} ✕
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}
