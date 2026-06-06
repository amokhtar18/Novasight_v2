/**
 * TableRenderer — renders a QueryResponse as an accessible HTML table.
 *
 * Used for `ChartSpec.type === "table"` (which ECharts does not render) and as a
 * raw-data view elsewhere. Column order follows the spec's encoding when present
 * (x first, then series fields), otherwise the response's own column order.
 */

import { cn } from "@/lib/cn";
import { formatCell, humanize } from "@/lib/format";
import type { ChartSpec, QueryResponse } from "@/types/api";

interface TableRendererProps {
  data: QueryResponse;
  /** Optional spec — when present, its encoding controls column order/labels. */
  spec?: ChartSpec;
  className?: string;
  /** Cap rows shown (the rest are summarised in a footer). */
  maxRows?: number;
}

export function TableRenderer({
  data,
  spec,
  className,
  maxRows = 100,
}: TableRendererProps) {
  const { columns, rows } = data;

  // Resolve display columns: spec encoding order if it maps onto real columns.
  let displayCols = columns;
  if (spec) {
    const wanted = [
      ...(spec.encoding.x ? [spec.encoding.x] : []),
      ...spec.encoding.series.map((s) => s.field),
    ].filter((c) => columns.includes(c));
    if (wanted.length) displayCols = wanted;
  }
  const colIdx = displayCols.map((c) => columns.indexOf(c));
  const shown = rows.slice(0, maxRows);

  return (
    <div className={cn("overflow-auto rounded-lg border", className)}>
      <table className="w-full border-collapse text-sm">
        <thead className="sticky top-0 bg-muted/70 backdrop-blur">
          <tr>
            {displayCols.map((c) => (
              <th
                key={c}
                scope="col"
                className="whitespace-nowrap px-3 py-2 text-left font-medium text-muted-foreground"
              >
                {humanize(c)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shown.map((row, r) => (
            <tr
              key={r}
              className="border-t border-border/60 transition-colors hover:bg-muted/40"
            >
              {colIdx.map((ci, c) => (
                <td
                  key={c}
                  className={cn(
                    "px-3 py-2",
                    typeof row[ci] === "number"
                      ? "text-right tabular-nums"
                      : "text-left"
                  )}
                >
                  {formatCell(row[ci])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > shown.length && (
        <p className="border-t bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
          Showing {shown.length} of {rows.length} rows.
        </p>
      )}
    </div>
  );
}
