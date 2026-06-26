/**
 * NumberRenderer — a single "big number" KPI tile for `ChartSpec.type === "number"`.
 *
 * Like the table renderer, a number is not an ECharts option; it presents a query
 * result directly. It shows the **total of the first series** across the returned
 * rows (so a single-aggregate query shows that value, and a grouped query shows the
 * grand total), with the series label underneath.
 *
 * v2 (Slice A2): Reads `spec.options?.type_options?.number` for subheader/subtitle
 * text and header_font_size/subheader_font_size, and formats the main value via
 * `formatChartValue` when `spec.options?.number_format` is set.
 */

import { cn } from "@/lib/cn";
import { formatChartValue } from "@/lib/chartFormat";
import { humanize } from "@/lib/format";
import type { ChartSpec, QueryResponse } from "@/types/api";

interface NumberRendererProps {
  spec: ChartSpec;
  data: QueryResponse;
  className?: string;
}

export function NumberRenderer({ spec, data, className }: NumberRendererProps) {
  const { columns, rows } = data;
  const series = spec.encoding.series[0];
  const idx = series ? columns.indexOf(series.field) : -1;

  // Sum the series column across rows (non-numeric/null cells contribute 0).
  const total =
    idx === -1
      ? null
      : rows.reduce((sum, row) => {
          const v = row[idx];
          return sum + (typeof v === "number" ? v : 0);
        }, 0);

  const label = series ? series.name ?? humanize(series.field) : "";

  // v2: number-family options
  const numberOpts = spec.options?.type_options?.number;
  const numberFormat = spec.options?.number_format;

  // Format main value: use formatChartValue when number_format is present,
  // otherwise fall back to the raw localized string to preserve existing behaviour.
  const formattedTotal =
    total === null
      ? "—"
      : numberFormat
        ? formatChartValue(total, numberFormat)
        : total.toLocaleString();

  const headerFontSize = numberOpts?.header_font_size;
  const subheaderFontSize = numberOpts?.subheader_font_size;

  return (
    <div
      className={cn(
        "flex h-80 flex-col items-center justify-center rounded-lg border bg-card/40 p-6 text-center",
        className
      )}
    >
      {spec.options?.title && (
        <p className="mb-2 text-sm font-medium text-muted-foreground">{spec.options.title}</p>
      )}
      <p
        className="text-5xl font-semibold tabular-nums tracking-tight"
        style={headerFontSize != null ? { fontSize: headerFontSize } : undefined}
      >
        {formattedTotal}
      </p>
      {label && <p className="mt-2 text-sm text-muted-foreground">{label}</p>}
      {numberOpts?.subheader && (
        <p
          className="mt-1 text-sm text-muted-foreground"
          style={subheaderFontSize != null ? { fontSize: subheaderFontSize } : undefined}
        >
          {numberOpts.subheader}
        </p>
      )}
      {numberOpts?.subtitle && (
        <p
          className="mt-1 text-xs text-muted-foreground"
          style={subheaderFontSize != null ? { fontSize: subheaderFontSize } : undefined}
        >
          {numberOpts.subtitle}
        </p>
      )}
    </div>
  );
}
