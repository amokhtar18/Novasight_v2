/**
 * NumberControls — per-family format panel for number (KPI tile) charts.
 *
 * Edits `options.type_options.number` via the immutable setFamily helper.
 * Covers: subheader/subtitle/header_font_size/subheader_font_size.
 */

import type { ChartOptions, NumberOptions } from "@/types/api";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { setFamily } from "./helpers";

interface Props {
  options: ChartOptions;
  setOptions: (o: ChartOptions) => void;
}

export function NumberControls({ options, setOptions }: Props) {
  const no: NumberOptions = options.type_options?.number ?? {};

  const set = (patch: Partial<NumberOptions>) =>
    setOptions(setFamily(options, "number", patch));

  const numOrNull = (s: string): number | null =>
    s.trim() !== "" && Number.isFinite(Number(s)) ? Number(s) : null;

  return (
    <details className="rounded-lg border bg-background/40 p-3">
      <summary className="cursor-pointer text-sm font-medium">KPI tile options</summary>
      <div className="mt-3 space-y-3">
        <div className="space-y-1.5">
          <Label htmlFor="nc-subheader">Subheader</Label>
          <Input
            id="nc-subheader"
            value={no.subheader ?? ""}
            onChange={(e) => set({ subheader: e.target.value || null })}
            placeholder="e.g. vs last month"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="nc-subtitle">Subtitle</Label>
          <Input
            id="nc-subtitle"
            value={no.subtitle ?? ""}
            onChange={(e) => set({ subtitle: e.target.value || null })}
            placeholder="Secondary text line"
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="nc-header-font-size">Header font size (px)</Label>
            <Input
              id="nc-header-font-size"
              value={no.header_font_size != null ? String(no.header_font_size) : ""}
              onChange={(e) => set({ header_font_size: numOrNull(e.target.value) })}
              placeholder="auto"
              inputMode="numeric"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="nc-subheader-font-size">Subheader font size (px)</Label>
            <Input
              id="nc-subheader-font-size"
              value={no.subheader_font_size != null ? String(no.subheader_font_size) : ""}
              onChange={(e) => set({ subheader_font_size: numOrNull(e.target.value) })}
              placeholder="auto"
              inputMode="numeric"
            />
          </div>
        </div>
      </div>
    </details>
  );
}
