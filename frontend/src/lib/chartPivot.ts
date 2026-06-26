/**
 * chartPivot — turn a long-form QueryResponse into wide form for breakdown series.
 *
 * A multi-dimension chart groups one measure by a category dimension (`encoding.x`)
 * **and** one or more breakdown dimensions (`encoding.breakdown`). The semantic layer
 * returns this in *long* form — one row per (x, breakdown…, measure) combination — but
 * the renderer plots one series per column. `applyBreakdown` pivots the breakdown
 * dimension values into one synthetic series column each, so the existing renderer can
 * draw a grouped/stacked chart without knowing anything about breakdowns.
 *
 * Pivoting only applies to multi-series category charts (bar/line/area/combo/radar) and
 * only when a breakdown is present; everything else is returned unchanged. The measure
 * pivoted is `series[0]` — the value channel of a breakdown chart is a single measure.
 */

import type { ChartSpec, ChartType, QueryResponse } from "@/types/api";

/** Chart types that plot multiple value series and so can show a breakdown. */
const PIVOTABLE: ReadonlySet<ChartType> = new Set<ChartType>([
  "bar",
  "hbar",
  "line",
  "area",
  "combo",
  "radar",
]);

/** Join one row's breakdown dimension values into a single series label. */
function seriesKey(row: QueryResponse["rows"][number], idxs: number[]): string {
  return idxs
    .map((i) => (row[i] === null || row[i] === undefined ? "(null)" : String(row[i])))
    .join(" / ");
}

/**
 * If `spec` carries breakdown dimensions and is a pivotable type, return a `{ spec, data }`
 * pair in wide form (one series column per distinct breakdown value); otherwise return the
 * inputs unchanged. Pure — never mutates its arguments.
 */
export function applyBreakdown(
  spec: ChartSpec,
  data: QueryResponse
): { spec: ChartSpec; data: QueryResponse } {
  const breakdown = spec.encoding.breakdown ?? [];
  const x = spec.encoding.x;
  const measure = spec.encoding.series[0];
  if (breakdown.length === 0 || !PIVOTABLE.has(spec.type) || !x || !measure) {
    return { spec, data };
  }

  const xIdx = data.columns.indexOf(x);
  const measureIdx = data.columns.indexOf(measure.field);
  const breakdownIdxs = breakdown.map((b) => data.columns.indexOf(b));
  // If any referenced column is missing, fall back to the raw spec rather than throw.
  if (xIdx === -1 || measureIdx === -1 || breakdownIdxs.some((i) => i === -1)) {
    return { spec, data };
  }

  // Preserve first-seen order for both axes so the chart is deterministic.
  const xOrder: string[] = [];
  const seriesOrder: string[] = [];
  // xKey -> seriesKey -> summed measure value
  const cells = new Map<string, Map<string, number>>();

  for (const row of data.rows) {
    const xKey = row[xIdx] === null || row[xIdx] === undefined ? "(null)" : String(row[xIdx]);
    const sKey = seriesKey(row, breakdownIdxs);
    const value = row[measureIdx] === null || row[measureIdx] === undefined ? 0 : Number(row[measureIdx]);

    if (!cells.has(xKey)) {
      cells.set(xKey, new Map());
      xOrder.push(xKey);
    }
    if (!seriesOrder.includes(sKey)) seriesOrder.push(sKey);
    const bucket = cells.get(xKey)!;
    bucket.set(sKey, (bucket.get(sKey) ?? 0) + (Number.isFinite(value) ? value : 0));
  }

  const columns = [x, ...seriesOrder];
  const rows = xOrder.map((xKey) => {
    const bucket = cells.get(xKey)!;
    return [xKey, ...seriesOrder.map((s) => bucket.get(s) ?? null)];
  });

  const pivoted: ChartSpec = {
    ...spec,
    encoding: {
      ...spec.encoding,
      x,
      series: seriesOrder.map((s) => ({ field: s, name: s })),
      breakdown: [],
    },
  };

  return { spec: pivoted, data: { columns, rows, row_count: rows.length } };
}
