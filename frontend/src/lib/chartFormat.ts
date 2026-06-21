/**
 * Numeric value formatting for charts (#8) — shared by the renderer for axis
 * labels, tooltips, and value displays. Honors a spec's NumberFormat (plain /
 * currency / percent, fixed decimals, compact magnitudes).
 */

import type { NumberFormat } from "@/types/api";

/** Format `value` per `nf`. Null/non-finite values render as an empty string. */
export function formatChartValue(value: number, nf?: NumberFormat): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "";
  const style = nf?.style ?? "plain";
  const decimals = nf?.decimals ?? null;
  const compact = nf?.compact ?? false;
  const body = compact ? compactNumber(value, decimals) : plainNumber(value, decimals);
  if (style === "currency") return `${nf?.currency ?? "$"}${body}`;
  if (style === "percent") return `${body}%`;
  return body;
}

function plainNumber(n: number, decimals: number | null): string {
  return decimals != null
    ? n.toLocaleString(undefined, {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      })
    : n.toLocaleString();
}

function compactNumber(n: number, decimals: number | null): string {
  const abs = Math.abs(n);
  const units: [number, string][] = [
    [1e12, "T"],
    [1e9, "B"],
    [1e6, "M"],
    [1e3, "K"],
  ];
  for (const [divisor, suffix] of units) {
    if (abs >= divisor) return `${(n / divisor).toFixed(decimals ?? 1)}${suffix}`;
  }
  return decimals != null ? n.toFixed(decimals) : String(n);
}
