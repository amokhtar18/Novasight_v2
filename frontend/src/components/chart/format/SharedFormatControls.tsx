/**
 * SharedFormatControls — the common formatting chrome rendered for every chart type.
 *
 * Covers: title, color_scheme, legend (show/position/type/margin/sort),
 * number_format (style/decimals/compact/currency/prefix/suffix), date_format,
 * labels (show/position/template/threshold), tooltip (mode/sort_by_metric/
 * show_total/show_percentage/time_format), sort.
 *
 * Reads/writes `ChartOptions` via an immutable updater pattern — a shallow merge
 * at the `options` level and at each sub-object level.
 */

import type { ChartOptions, ChartSort, LegendOptions, NumberFormat, LabelOptions, TooltipOptions } from "@/types/api";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Checkbox } from "@/components/ui/checkbox";
import { humanize } from "@/lib/format";
import { COLOR_SCHEMES } from "@/lib/colorSchemes";

// Derive the dropdown entries from the single source of truth so the UI stays in sync
// with the palette map used by the renderer.
const COLOR_SCHEME_KEYS = Object.keys(COLOR_SCHEMES);

const SORT_OPTIONS: ChartSort[] = [
  "none",
  "value_desc",
  "value_asc",
  "label_asc",
  "label_desc",
];

const LEGEND_POSITIONS = ["top", "bottom", "left", "right"] as const;
const LEGEND_TYPES = ["plain", "scroll"] as const;
const LEGEND_SORTS = ["none", "asc", "desc"] as const;

const NUMBER_STYLES: NonNullable<NumberFormat["style"]>[] = ["plain", "currency", "percent"];

const TOOLTIP_MODES = ["item", "axis", "rich"] as const;

interface Props {
  options: ChartOptions;
  setOptions: (o: ChartOptions) => void;
}

/** Keys of ChartOptions whose values are plain sub-objects (not primitives). */
type ObjectKey = {
  [K in keyof ChartOptions]-?: NonNullable<ChartOptions[K]> extends object ? K : never;
}[keyof ChartOptions];

/** Immutably merge a partial sub-object into `options` for object-valued keys only. */
function setSubKey<K extends ObjectKey>(
  options: ChartOptions,
  key: K,
  patch: Partial<NonNullable<ChartOptions[K]>>
): ChartOptions {
  const existing = options[key] as object | undefined | null;
  return {
    ...options,
    [key]: { ...(existing ?? {}), ...patch } as ChartOptions[K],
  };
}

export function SharedFormatControls({ options, setOptions }: Props) {
  const legend: LegendOptions = options.legend ?? {};
  const nf: NumberFormat = options.number_format ?? {};
  const labels: LabelOptions = options.labels ?? {};
  const tooltip: TooltipOptions = options.tooltip ?? {};

  const setLegend = (patch: Partial<LegendOptions>) =>
    setOptions(setSubKey(options, "legend", patch));
  const setNf = (patch: Partial<NumberFormat>) =>
    setOptions(setSubKey(options, "number_format", patch));
  const setLabels = (patch: Partial<LabelOptions>) =>
    setOptions(setSubKey(options, "labels", patch));
  const setTooltip = (patch: Partial<TooltipOptions>) =>
    setOptions(setSubKey(options, "tooltip", patch));

  const numOrNull = (s: string): number | null =>
    s.trim() !== "" && Number.isFinite(Number(s)) ? Number(s) : null;

  return (
    <div className="space-y-4">
      {/* Title */}
      <details className="rounded-lg border bg-background/40 p-3" open>
        <summary className="cursor-pointer text-sm font-medium">General</summary>
        <div className="mt-3 space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="sf-title">Chart title</Label>
            <Input
              id="sf-title"
              value={options.title ?? ""}
              onChange={(e) => setOptions({ ...options, title: e.target.value || null })}
              placeholder="Auto-generated title"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="sf-color-scheme">Color scheme</Label>
            <Select
              id="sf-color-scheme"
              value={options.color_scheme ?? "default"}
              onChange={(e) => setOptions({ ...options, color_scheme: e.target.value || null })}
            >
              {COLOR_SCHEME_KEYS.map((cs) => (
                <option key={cs} value={cs}>
                  {humanize(cs)}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="sf-sort">Sort</Label>
            <Select
              id="sf-sort"
              value={options.sort ?? "none"}
              onChange={(e) => setOptions({ ...options, sort: e.target.value as ChartSort })}
            >
              {SORT_OPTIONS.map((s) => (
                <option key={s} value={s}>
                  {humanize(s)}
                </option>
              ))}
            </Select>
          </div>
        </div>
      </details>

      {/* Legend */}
      <details className="rounded-lg border bg-background/40 p-3">
        <summary className="cursor-pointer text-sm font-medium">Legend</summary>
        <div className="mt-3 space-y-3">
          <div className="flex items-center gap-2">
            <Checkbox
              id="sf-legend-show"
              checked={legend.show !== false}
              onChange={(e) => setLegend({ show: e.target.checked })}
            />
            <Label htmlFor="sf-legend-show">Show legend</Label>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="sf-legend-position">Position</Label>
              <Select
                id="sf-legend-position"
                value={legend.position ?? "top"}
                onChange={(e) =>
                  setLegend({ position: e.target.value as LegendOptions["position"] })
                }
              >
                {LEGEND_POSITIONS.map((p) => (
                  <option key={p} value={p}>
                    {humanize(p)}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="sf-legend-type">Type</Label>
              <Select
                id="sf-legend-type"
                value={legend.type ?? "plain"}
                onChange={(e) =>
                  setLegend({ type: e.target.value as LegendOptions["type"] })
                }
              >
                {LEGEND_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {humanize(t)}
                  </option>
                ))}
              </Select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="sf-legend-margin">Margin (px)</Label>
              <Input
                id="sf-legend-margin"
                value={legend.margin != null ? String(legend.margin) : ""}
                onChange={(e) => setLegend({ margin: numOrNull(e.target.value) })}
                placeholder="auto"
                inputMode="numeric"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="sf-legend-sort">Sort</Label>
              <Select
                id="sf-legend-sort"
                value={legend.sort ?? "none"}
                onChange={(e) =>
                  setLegend({ sort: e.target.value as LegendOptions["sort"] })
                }
              >
                {LEGEND_SORTS.map((s) => (
                  <option key={s} value={s}>
                    {humanize(s)}
                  </option>
                ))}
              </Select>
            </div>
          </div>
        </div>
      </details>

      {/* Number format */}
      <details className="rounded-lg border bg-background/40 p-3">
        <summary className="cursor-pointer text-sm font-medium">Number format</summary>
        <div className="mt-3 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="sf-nf-style">Style</Label>
              <Select
                id="sf-nf-style"
                value={nf.style ?? "plain"}
                onChange={(e) => setNf({ style: e.target.value as NumberFormat["style"] })}
              >
                {NUMBER_STYLES.map((s) => (
                  <option key={s} value={s}>
                    {humanize(s)}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="sf-nf-decimals">Decimals</Label>
              <Input
                id="sf-nf-decimals"
                value={nf.decimals != null ? String(nf.decimals) : ""}
                onChange={(e) => setNf({ decimals: numOrNull(e.target.value) })}
                placeholder="auto"
                inputMode="numeric"
              />
            </div>
          </div>
          {nf.style === "currency" && (
            <div className="space-y-1.5">
              <Label htmlFor="sf-nf-currency">Currency code</Label>
              <Input
                id="sf-nf-currency"
                value={nf.currency ?? ""}
                onChange={(e) => setNf({ currency: e.target.value || null })}
                placeholder="USD"
              />
            </div>
          )}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="sf-nf-prefix">Prefix</Label>
              <Input
                id="sf-nf-prefix"
                value={nf.prefix ?? ""}
                onChange={(e) => setNf({ prefix: e.target.value || null })}
                placeholder="e.g. ≈"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="sf-nf-suffix">Suffix</Label>
              <Input
                id="sf-nf-suffix"
                value={nf.suffix ?? ""}
                onChange={(e) => setNf({ suffix: e.target.value || null })}
                placeholder="e.g. /u"
              />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Checkbox
              id="sf-nf-compact"
              checked={nf.compact ?? false}
              onChange={(e) => setNf({ compact: e.target.checked })}
            />
            <Label htmlFor="sf-nf-compact">Compact notation</Label>
          </div>
        </div>
      </details>

      {/* Date format */}
      <details className="rounded-lg border bg-background/40 p-3">
        <summary className="cursor-pointer text-sm font-medium">Date format</summary>
        <div className="mt-3 space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="sf-date-format">Format string</Label>
            <Input
              id="sf-date-format"
              value={options.date_format ?? ""}
              onChange={(e) =>
                setOptions({ ...options, date_format: e.target.value || null })
              }
              placeholder="e.g. YYYY-MM-DD"
            />
          </div>
        </div>
      </details>

      {/* Data labels */}
      <details className="rounded-lg border bg-background/40 p-3">
        <summary className="cursor-pointer text-sm font-medium">Data labels</summary>
        <div className="mt-3 space-y-3">
          <div className="flex items-center gap-2">
            <Checkbox
              id="sf-labels-show"
              checked={labels.show ?? false}
              onChange={(e) => setLabels({ show: e.target.checked })}
            />
            <Label htmlFor="sf-labels-show">Show data labels</Label>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="sf-labels-position">Position</Label>
              <Input
                id="sf-labels-position"
                value={labels.position ?? ""}
                onChange={(e) => setLabels({ position: e.target.value || null })}
                placeholder="e.g. top, inside"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="sf-labels-threshold">Threshold</Label>
              <Input
                id="sf-labels-threshold"
                value={labels.threshold != null ? String(labels.threshold) : ""}
                onChange={(e) => setLabels({ threshold: numOrNull(e.target.value) })}
                placeholder="min value to show"
                inputMode="numeric"
              />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="sf-labels-template">Template</Label>
            <Input
              id="sf-labels-template"
              value={labels.template ?? ""}
              onChange={(e) => setLabels({ template: e.target.value || null })}
              placeholder="e.g. {c}%"
            />
          </div>
        </div>
      </details>

      {/* Tooltip */}
      <details className="rounded-lg border bg-background/40 p-3">
        <summary className="cursor-pointer text-sm font-medium">Tooltip</summary>
        <div className="mt-3 space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="sf-tooltip-mode">Mode</Label>
            <Select
              id="sf-tooltip-mode"
              value={tooltip.mode ?? "axis"}
              onChange={(e) =>
                setTooltip({ mode: e.target.value as TooltipOptions["mode"] })
              }
            >
              {TOOLTIP_MODES.map((m) => (
                <option key={m} value={m}>
                  {humanize(m)}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="sf-tooltip-time-format">Time format</Label>
            <Input
              id="sf-tooltip-time-format"
              value={tooltip.time_format ?? ""}
              onChange={(e) => setTooltip({ time_format: e.target.value || null })}
              placeholder="e.g. YYYY-MM-DD HH:mm"
            />
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-2 text-sm">
            <label className="flex items-center gap-2">
              <Checkbox
                checked={tooltip.sort_by_metric ?? false}
                onChange={(e) => setTooltip({ sort_by_metric: e.target.checked })}
              />
              Sort by metric
            </label>
            <label className="flex items-center gap-2">
              <Checkbox
                checked={tooltip.show_total ?? false}
                onChange={(e) => setTooltip({ show_total: e.target.checked })}
              />
              Show total
            </label>
            <label className="flex items-center gap-2">
              <Checkbox
                checked={tooltip.show_percentage ?? false}
                onChange={(e) => setTooltip({ show_percentage: e.target.checked })}
              />
              Show percentage
            </label>
          </div>
        </div>
      </details>
    </div>
  );
}
