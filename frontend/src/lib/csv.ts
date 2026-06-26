/**
 * CSV export for a QueryResponse. RFC-4180 escaping: a field is quoted when it
 * contains a comma, double-quote, or newline, and embedded quotes are doubled.
 */
import type { QueryResponse } from "@/types/api";

function escapeField(value: unknown): string {
  if (value === null || value === undefined) return "";
  const s = String(value);
  if (/[",\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

/** Serialise a QueryResponse to a CSV string (header row + data rows). */
export function toCsv(data: QueryResponse): string {
  const header = data.columns.map(escapeField).join(",");
  const rows = data.rows.map((row) => row.map(escapeField).join(","));
  return [header, ...rows].join("\n");
}

/** Trigger a browser download of the QueryResponse as a .csv file. */
export function downloadCsv(data: QueryResponse, filename: string): void {
  const blob = new Blob([toCsv(data)], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename.endsWith(".csv") ? filename : `${filename}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
