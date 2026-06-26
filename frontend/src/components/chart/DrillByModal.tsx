/**
 * DrillByModal — pivot a chart by another governed dimension of the same cube,
 * optionally focused on one point. Runs a grounded /semantic/query via useChartData
 * (no backend change) and renders the result with the shared ChartRenderer.
 *
 * Golden rule #3: buildDrillBySpec only sets query.metric_refs/dimensions/filters +
 * encoding — no raw SQL is ever produced or forwarded.
 */
import { useMemo, useState } from "react";

import { useSemanticModels } from "@/api/hooks";
import { useChartData } from "@/lib/useChartData";
import { ChartRenderer } from "@/components/chart/ChartRenderer";
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select } from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/ui/spinner";
import { EmptyState } from "@/components/ui/empty-state";
import { cubeOf } from "@/lib/dashboardFilters";
import type { ChartSpec, QueryResponse, SemanticFilter } from "@/types/api";

/**
 * Build a derived ChartSpec that re-groups by `dimension`, filters to the chosen
 * `point` (when non-null), and merges any `extraFilters` (the tile's active
 * dashboard filters). Number/table types are coerced to bar since they have no
 * meaningful category axis to re-pivot.
 *
 * The output is always grounded: metric_refs is carried from the base spec unchanged;
 * only dimensions, time_dimensions, filters, and encoding are modified.
 */
export function buildDrillBySpec(
  base: ChartSpec,
  dimension: string,
  point: { member: string; value: string } | null,
  extraFilters: SemanticFilter[]
): ChartSpec {
  const pointFilter: SemanticFilter[] = point
    ? [{ member: point.member, operator: "equals", values: [point.value] }]
    : [];
  return {
    ...base,
    type: base.type === "number" || base.type === "table" ? "bar" : base.type,
    query: {
      ...base.query,
      dimensions: [dimension],
      time_dimensions: [],
      filters: [...(base.query.filters ?? []), ...extraFilters, ...pointFilter],
    },
    encoding: { x: dimension, series: base.encoding.series, breakdown: [] },
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

export function DrillByModal({ open, onOpenChange, spec, tileFilters, data }: Props) {
  const { data: models } = useSemanticModels();
  const baseCube = cubeOf((spec.query.metric_refs ?? [])[0]);
  const baseX = spec.encoding.x;

  // Other governed dimensions on the same cube (excluding the current x axis).
  const dimensionOptions = useMemo(() => {
    const model = (models ?? []).find((m) => m.name === baseCube);
    return (model?.dimensions ?? []).filter((d) => d.name !== baseX);
  }, [models, baseCube, baseX]);

  const [dimension, setDimension] = useState("");
  const [focus, setFocus] = useState(""); // "" = all points

  // Candidate focus points: distinct x-column values present in the tile's data.
  const xIndex = baseX ? data.columns.indexOf(baseX) : -1;
  const points =
    xIndex >= 0
      ? Array.from(new Set(data.rows.map((r) => String((r as unknown[])[xIndex]))))
      : [];

  const derived = dimension
    ? buildDrillBySpec(
        spec,
        dimension,
        focus && baseX ? { member: baseX, value: focus } : null,
        tileFilters
      )
    : null;
  const { data: result, isLoading } = useChartData(derived);

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Drill by">
      <DialogHeader>
        <DialogTitle>Drill by</DialogTitle>
      </DialogHeader>
      <div className="space-y-3">
        <div className="flex gap-3">
          <div className="flex-1 space-y-1">
            <Label htmlFor="drill-dim">Dimension</Label>
            <Select
              id="drill-dim"
              value={dimension}
              onChange={(e) => setDimension(e.target.value)}
            >
              <option value="">Choose…</option>
              {dimensionOptions.map((d) => (
                <option key={d.name} value={d.name}>
                  {d.title}
                </option>
              ))}
            </Select>
          </div>
          {points.length > 0 && (
            <div className="flex-1 space-y-1">
              <Label htmlFor="drill-focus">Focus ({baseX})</Label>
              <Select
                id="drill-focus"
                value={focus}
                onChange={(e) => setFocus(e.target.value)}
              >
                <option value="">All</option>
                {points.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </Select>
            </div>
          )}
        </div>
        <div className="h-72">
          {!derived ? (
            <EmptyState
              title="Pick a dimension"
              description="Choose a dimension to drill by."
            />
          ) : isLoading ? (
            <div className="flex h-full items-center justify-center">
              <Spinner label="Loading" />
            </div>
          ) : result && result.row_count > 0 ? (
            <ChartRenderer
              spec={derived}
              data={result}
              title="Drill by"
              className="h-72"
            />
          ) : (
            <EmptyState title="No data" description="This drill returned no rows." />
          )}
        </div>
      </div>
    </Dialog>
  );
}
