/**
 * DrillToDetailModal — a grounded detail breakdown of a clicked point (Slice C).
 * Golden rule #3: NOT raw rows — it re-queries the semantic layer for the metric(s)
 * broken down by the cube's remaining governed dimensions, filtered to the point.
 */
import { useMemo, useState } from "react";

import { useSemanticModels, useSemanticQuery } from "@/api/hooks";
import { TableRenderer } from "@/components/chart/TableRenderer";
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select } from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/ui/spinner";
import { EmptyState } from "@/components/ui/empty-state";
import { cubeOf } from "@/lib/dashboardFilters";
import type { ChartSpec, QueryResponse, SemanticFilter, SemanticModelRead, SemanticQueryRequest } from "@/types/api";

/**
 * Build a SemanticQueryRequest that re-queries the metric(s) from spec broken
 * down by every governed dimension on the same cube that is NOT already encoded
 * (i.e. not in spec.query.dimensions and not spec.encoding.x). Filters are the
 * union of spec.query.filters, extraFilters, and an optional point filter.
 */
export function buildDetailRequest(
  spec: ChartSpec,
  models: SemanticModelRead[],
  point: { member: string; value: string } | null,
  extraFilters: SemanticFilter[]
): SemanticQueryRequest | null {
  const cube = cubeOf((spec.query.metric_refs ?? [])[0]);
  const model = models.find((m) => m.name === cube);
  const measures = spec.query.metric_refs ?? [];
  if (!model || measures.length === 0) return null;
  const encoded = new Set<string>([
    ...(spec.query.dimensions ?? []),
    ...(spec.encoding.breakdown ?? []),
    ...(spec.encoding.x ? [spec.encoding.x] : []),
  ]);
  const dimensions = model.dimensions.map((d) => d.name).filter((n) => !encoded.has(n));
  const pointFilter: SemanticFilter[] = point
    ? [{ member: point.member, operator: "equals", values: [point.value] }]
    : [];
  return {
    measures,
    dimensions,
    filters: [...(spec.query.filters ?? []), ...extraFilters, ...pointFilter],
  };
}

interface Props {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  spec: ChartSpec;
  tileFilters: SemanticFilter[];
  /** The QueryResponse already loaded by the tile — provides candidate focus points. */
  data: QueryResponse;
}

export function DrillToDetailModal({ open, onOpenChange, spec, tileFilters, data }: Props) {
  const { data: models } = useSemanticModels();
  const baseX = spec.encoding.x;
  const xIndex = baseX ? data.columns.indexOf(baseX) : -1;
  const points = xIndex >= 0 ? Array.from(new Set(data.rows.map((r) => String((r as unknown[])[xIndex])))) : [];
  const [focus, setFocus] = useState("");

  const req = useMemo(
    () => buildDetailRequest(spec, models ?? [], focus && baseX ? { member: baseX, value: focus } : null, tileFilters),
    [spec, models, focus, baseX, tileFilters]
  );
  const { data: result, isLoading } = useSemanticQuery(open ? req : null);

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Drill to detail">
      <DialogHeader><DialogTitle>Drill to detail</DialogTitle></DialogHeader>
      <div className="space-y-3">
        {points.length > 0 && (
          <div className="space-y-1">
            <Label htmlFor="detail-focus">Focus ({baseX})</Label>
            <Select id="detail-focus" value={focus} onChange={(e) => setFocus(e.target.value)}>
              <option value="">All</option>
              {points.map((p) => (<option key={p} value={p}>{p}</option>))}
            </Select>
          </div>
        )}
        <div className="max-h-96 overflow-auto">
          {isLoading ? (
            <div className="flex h-40 items-center justify-center"><Spinner label="Loading detail" /></div>
          ) : result && result.row_count > 0 ? (
            <TableRenderer data={result} />
          ) : (
            <EmptyState title="No detail" description="This breakdown returned no rows." />
          )}
        </div>
      </div>
    </Dialog>
  );
}
