/**
 * QueryControls — Superset-Explore query shaping for the builder (Slice A):
 * time range (when the x-axis is a time dimension), server "Sort by", and row limit.
 * Filters live on their own shelf in SemanticQueryBuilder.
 */
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { humanize } from "@/lib/format";
import type { RelativeDateRange } from "@/types/api";
import type { SemanticBuilder } from "@/pages/Builder";

const RELATIVE_RANGES: RelativeDateRange[] = [
  "last_7_days",
  "last_30_days",
  "last_90_days",
  "this_month",
  "last_month",
  "this_quarter",
  "last_quarter",
  "this_year",
  "last_year",
];

export function QueryControls({ s }: { s: SemanticBuilder }) {
  // Sortable members = the queried measures + the category dimension.
  const sortMembers = [...s.measures, ...(s.xDim ? [s.xDim] : [])];
  const isCustom = Array.isArray(s.dateRange);

  return (
    <details className="rounded-lg border bg-background/40 p-3" open>
      <summary className="cursor-pointer text-sm font-medium">Query</summary>
      <div className="mt-3 space-y-3">
        {s.isTimeX && (
          <div className="space-y-1.5">
            <Label htmlFor="q-range">Time range</Label>
            <Select
              id="q-range"
              value={isCustom ? "custom" : (s.dateRange ?? "none")}
              onChange={(e) => {
                const v = e.target.value;
                if (v === "none") s.setDateRange(null);
                else if (v === "custom") s.setDateRange(["", ""]);
                else s.setDateRange(v as RelativeDateRange);
              }}
            >
              <option value="none">No filter</option>
              {RELATIVE_RANGES.map((r) => (
                <option key={r} value={r}>{humanize(r)}</option>
              ))}
              <option value="custom">Custom range…</option>
            </Select>
            {isCustom && (
              <div className="grid grid-cols-2 gap-2">
                <Input
                  type="date"
                  aria-label="From"
                  value={(s.dateRange as string[])[0]}
                  onChange={(e) => s.setDateRange([e.target.value, (s.dateRange as string[])[1]])}
                />
                <Input
                  type="date"
                  aria-label="To"
                  value={(s.dateRange as string[])[1]}
                  onChange={(e) => s.setDateRange([(s.dateRange as string[])[0], e.target.value])}
                />
              </div>
            )}
          </div>
        )}

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="q-sort">Sort by (query)</Label>
            <Select
              id="q-sort"
              value={s.orderBy?.member ?? ""}
              onChange={(e) =>
                s.setOrderBy(e.target.value ? { member: e.target.value, dir: s.orderBy?.dir ?? "desc" } : null)
              }
            >
              <option value="">None</option>
              {sortMembers.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="q-dir">Direction</Label>
            <Select
              id="q-dir"
              value={s.orderBy?.dir ?? "desc"}
              disabled={!s.orderBy}
              onChange={(e) =>
                s.orderBy && s.setOrderBy({ member: s.orderBy.member, dir: e.target.value as "asc" | "desc" })
              }
            >
              <option value="desc">Descending</option>
              <option value="asc">Ascending</option>
            </Select>
          </div>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="q-limit">Row limit</Label>
          <Input
            id="q-limit"
            type="number"
            min={1}
            value={s.rowLimit}
            onChange={(e) => s.setRowLimit(Math.max(1, Number(e.target.value) || 1))}
          />
        </div>
      </div>
    </details>
  );
}
