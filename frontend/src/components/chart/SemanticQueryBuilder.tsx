/**
 * SemanticQueryBuilder — the drag-and-drop, Superset-inspired chart configurator.
 *
 * The left "Data" palette lists every governed dimension and measure of the chosen
 * model as draggable chips. The user drags (or clicks) them onto three shelves:
 *   • X-axis    — one dimension (the category axis / time axis)
 *   • Breakdown — any number of dimensions, pivoted into one series each
 *   • Metrics   — one or more measures (the value channel)
 * The shelves drive the same ChartSpec the renderer and the AI path emit, so a
 * multi-dimension chart needs no special rendering — `applyBreakdown` pivots it.
 *
 * Drag-and-drop uses @dnd-kit/core (same library as the dashboard grid). A field can
 * only land on a shelf that accepts its kind; clicking a palette chip adds it to the
 * sensible default shelf. Nothing here is hardcoded or tenant-specific — every field
 * comes from the governed model meta.
 */

import { useState } from "react";
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  pointerWithin,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { GripVertical, Hash, Ruler, Tag, X } from "lucide-react";

import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { humanize } from "@/lib/format";
import { cn } from "@/lib/cn";
import type { ChartType, SemanticField, SemanticFilter, SemanticFilterOperator } from "@/types/api";
import type { SemanticBuilder } from "@/pages/Builder";

const CHART_TYPES: ChartType[] = [
  "bar",
  "hbar",
  "line",
  "area",
  "combo",
  "pie",
  "donut",
  "scatter",
  "funnel",
  "treemap",
  "radar",
  "gauge",
  "heatmap",
  "sankey",
  "table",
  "number",
];

const GRANULARITIES = ["day", "week", "month", "quarter", "year"] as const;

/** What a draggable field carries, read back in `onDragEnd`. */
type FieldKind = "dimension" | "measure";
interface DragData {
  field: string;
  kind: FieldKind;
}

const SHELF_ACCEPTS: Record<string, FieldKind> = {
  x: "dimension",
  breakdown: "dimension",
  metrics: "measure",
};

// ---------------------------------------------------------------------------
// Filter helpers (exported for unit tests)
// ---------------------------------------------------------------------------

/** Append a default `equals` filter for a member, unless it is already filtered. */
export function filtersAfterDrop(filters: SemanticFilter[], member: string): SemanticFilter[] {
  if (filters.some((f) => f.member === member)) return filters;
  return [...filters, { member, operator: "equals", values: [] }];
}

/** Split a comma-separated values string into trimmed, non-empty values. */
export function parseFilterValues(raw: string): string[] {
  return raw
    .split(",")
    .map((v) => v.trim())
    .filter(Boolean);
}

const FILTER_OPERATORS: SemanticFilterOperator[] = [
  "equals",
  "notEquals",
  "contains",
  "notContains",
  "gt",
  "gte",
  "lt",
  "lte",
  "set",
  "notSet",
];

const VALUELESS_OPERATORS: SemanticFilterOperator[] = ["set", "notSet"];

// ---------------------------------------------------------------------------
// Draggable palette chip + placed (removable) chip
// ---------------------------------------------------------------------------

function fieldTitle(fields: SemanticField[] | undefined, name: string): string {
  return fields?.find((f) => f.name === name)?.title ?? name;
}

function PaletteChip({
  field,
  kind,
  onAdd,
}: {
  field: SemanticField;
  kind: FieldKind;
  onAdd: () => void;
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `palette:${kind}:${field.name}`,
    data: { field: field.name, kind } satisfies DragData,
  });
  const Icon = kind === "measure" ? Ruler : field.type === "time" ? Hash : Tag;
  return (
    <button
      type="button"
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      onClick={onAdd}
      title={`${field.title} — drag to a shelf or click to add`}
      className={cn(
        "flex w-full items-center gap-1.5 rounded-md border bg-background/60 px-2 py-1 text-left text-xs",
        "cursor-grab hover:border-primary/50 hover:bg-primary/5 active:cursor-grabbing",
        isDragging && "opacity-40"
      )}
    >
      <Icon className="h-3 w-3 shrink-0 text-muted-foreground" aria-hidden />
      <span className="truncate">{field.title}</span>
    </button>
  );
}

function PlacedChip({ label, onRemove }: { label: string; onRemove: () => void }) {
  return (
    <span className="inline-flex max-w-full items-center gap-1 rounded-md border bg-primary/10 px-2 py-1 text-xs">
      <span className="truncate">{label}</span>
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Remove ${label}`}
        className="rounded p-0.5 text-muted-foreground hover:bg-destructive/15 hover:text-destructive"
      >
        <X className="h-3 w-3" />
      </button>
    </span>
  );
}

function Shelf({
  id,
  label,
  hint,
  children,
  empty,
}: {
  id: string;
  label: string;
  hint?: string;
  children: React.ReactNode;
  empty: boolean;
}) {
  const { setNodeRef, isOver, active } = useDroppable({ id });
  // The "filters" shelf accepts both dimensions and measures; all other shelves are keyed.
  const accepted =
    id === "filters"
      ? !!(active?.data.current as DragData | undefined)?.kind
      : (active?.data.current as DragData | undefined)?.kind === SHELF_ACCEPTS[id];
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      <div
        ref={setNodeRef}
        className={cn(
          "flex min-h-[2.5rem] flex-wrap content-start gap-1.5 rounded-lg border border-dashed bg-background/40 p-2 transition-colors",
          isOver && accepted && "border-primary bg-primary/5",
          isOver && active && !accepted && "border-destructive/60"
        )}
      >
        {empty ? (
          <span className="self-center text-xs text-muted-foreground">{hint}</span>
        ) : (
          children
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// BuilderDnd — owns the DndContext, sensors, drag label, and DragOverlay
// ---------------------------------------------------------------------------

export function BuilderDnd({ s, children }: { s: SemanticBuilder; children: React.ReactNode }) {
  const [dragLabel, setDragLabel] = useState<string | null>(null);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));

  function handleDragStart(e: DragStartEvent) {
    const data = e.active.data.current as DragData | undefined;
    if (data)
      setDragLabel(
        fieldTitle(
          data.kind === "measure" ? s.model?.measures ?? [] : s.model?.dimensions ?? [],
          data.field
        )
      );
  }

  function handleDragEnd(e: DragEndEvent) {
    setDragLabel(null);
    const data = e.active.data.current as DragData | undefined;
    const shelf = e.over?.id as string | undefined;
    if (!data || !shelf) return;
    if (shelf === "filters") {
      s.setFilters(filtersAfterDrop(s.filters, data.field));
      return;
    }
    if (SHELF_ACCEPTS[shelf] !== data.kind) return;
    if (shelf === "x") s.setXDim(data.field);
    else if (shelf === "breakdown") s.addBreakdown(data.field);
    else if (shelf === "metrics") s.addMeasure(data.field);
  }

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={pointerWithin}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
    >
      {children}
      <DragOverlay>
        {dragLabel ? (
          <span className="rounded-md border bg-card px-2 py-1 text-xs shadow-[var(--elevation-3)]">
            {dragLabel}
          </span>
        ) : null}
      </DragOverlay>
    </DndContext>
  );
}

// ---------------------------------------------------------------------------
// FieldsPalette — model Select + draggable Dimensions/Measures palette
// ---------------------------------------------------------------------------

export function FieldsPalette({ s }: { s: SemanticBuilder }) {
  if (s.modelsLoading) return <Spinner label="Loading fields" />;
  if (!s.models || s.models.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No semantic models are available yet. Create one over a data mart, then come back
        to build a chart on it.
      </p>
    );
  }

  const dims = s.model?.dimensions ?? [];
  const measures = s.model?.measures ?? [];
  const placedDims = new Set([s.xDim, ...s.breakdown].filter(Boolean));
  const placedMeasures = new Set(s.measures);

  return (
    <>
      <div className="space-y-1.5">
        <Label htmlFor="b-model">Model</Label>
        <Select
          id="b-model"
          value={s.modelName}
          onChange={(e) => s.setModelName(e.target.value)}
        >
          {s.models.map((m) => (
            <option key={m.name} value={m.name}>
              {m.title}
            </option>
          ))}
        </Select>
      </div>

      {/* Data palette — draggable governed fields. */}
      <div className="rounded-lg border bg-card/50 p-2">
        <div className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
          <GripVertical className="h-3 w-3" aria-hidden /> Data — drag a field onto a shelf
        </div>
        <p className="mb-1 text-[0.7rem] uppercase tracking-wide text-muted-foreground">
          Dimensions
        </p>
        <div className="mb-2 max-h-40 space-y-1 overflow-y-auto pr-1">
          {dims.length === 0 ? (
            <p className="text-xs text-muted-foreground">No dimensions</p>
          ) : (
            dims
              .filter((d) => !placedDims.has(d.name))
              .map((d) => (
                <PaletteChip
                  key={d.name}
                  field={d}
                  kind="dimension"
                  onAdd={() => (s.xDim ? s.addBreakdown(d.name) : s.setXDim(d.name))}
                />
              ))
          )}
        </div>
        <p className="mb-1 text-[0.7rem] uppercase tracking-wide text-muted-foreground">
          Measures
        </p>
        <div className="max-h-40 space-y-1 overflow-y-auto pr-1">
          {measures.length === 0 ? (
            <p className="text-xs text-muted-foreground">No measures</p>
          ) : (
            measures
              .filter((m) => !placedMeasures.has(m.name))
              .map((m) => (
                <PaletteChip
                  key={m.name}
                  field={m}
                  kind="measure"
                  onAdd={() => s.addMeasure(m.name)}
                />
              ))
          )}
        </div>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Shelves — X-axis, Breakdown, Metrics, Filters + granularity select
// ---------------------------------------------------------------------------

export function Shelves({ s }: { s: SemanticBuilder }) {
  const dims = s.model?.dimensions ?? [];
  const measures = s.model?.measures ?? [];

  return (
    <>
      {/* Shelves — responsive horizontal pills bar. */}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <div className="space-y-1.5">
          <Shelf id="x" label="X-axis" hint="Drop one dimension" empty={!s.xDim}>
            {s.xDim && (
              <PlacedChip label={fieldTitle(dims, s.xDim)} onRemove={() => s.setXDim("")} />
            )}
          </Shelf>
          {s.isTimeX && (
            <div className="space-y-1.5">
              <Label htmlFor="b-sem-gran">Granularity</Label>
              <Select
                id="b-sem-gran"
                value={s.granularity}
                onChange={(e) => s.setGranularity(e.target.value as (typeof GRANULARITIES)[number])}
              >
                {GRANULARITIES.map((g) => (
                  <option key={g} value={g}>
                    {humanize(g)}
                  </option>
                ))}
              </Select>
            </div>
          )}
        </div>

        <Shelf
          id="breakdown"
          label="Breakdown (series)"
          hint="Drop dimensions to split into series"
          empty={s.breakdown.length === 0}
        >
          {s.breakdown.map((b) => (
            <PlacedChip
              key={b}
              label={fieldTitle(dims, b)}
              onRemove={() => s.removeBreakdown(b)}
            />
          ))}
        </Shelf>

        <Shelf
          id="metrics"
          label="Metrics"
          hint="Drop one or more measures"
          empty={s.measures.length === 0}
        >
          {s.measures.map((m) => (
            <PlacedChip
              key={m}
              label={fieldTitle(measures, m)}
              onRemove={() => s.removeMeasure(m)}
            />
          ))}
        </Shelf>

        <Shelf
          id="filters"
          label="Filters"
          hint="Drop a field to filter on it"
          empty={s.filters.length === 0}
        >
          {s.filters.map((f) => (
            <FilterRow
              key={f.member}
              filter={f}
              onChange={(next) =>
                s.setFilters(s.filters.map((x) => (x.member === f.member ? next : x)))
              }
              onRemove={() => s.setFilters(s.filters.filter((x) => x.member !== f.member))}
            />
          ))}
        </Shelf>
      </div>

      {s.breakdown.length > 0 && s.measures.length > 1 && (
        <p className="text-[0.7rem] text-muted-foreground">
          With a breakdown, only the first metric ({fieldTitle(measures, s.measures[0])}) is
          plotted as series.
        </p>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// ChartTypeSelect — chart-type Select + heatmap/sankey hint
// ---------------------------------------------------------------------------

export function ChartTypeSelect({ s }: { s: SemanticBuilder }) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor="b-sem-type">Chart type</Label>
      <Select
        id="b-sem-type"
        value={s.chartType}
        onChange={(e) => s.setChartType(e.target.value as ChartType)}
      >
        {CHART_TYPES.map((t) => (
          <option key={t} value={t}>
            {humanize(t)}
          </option>
        ))}
      </Select>
      {(s.chartType === "heatmap" || s.chartType === "sankey") && (
        <p className="mt-1 text-xs text-muted-foreground">
          {s.chartType === "heatmap"
            ? "Add two dimensions (X, Y) and one measure — the measure colours each cell."
            : "Add two dimensions (Source, Target) and one measure — the measure is the flow weight."}
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// FilterRow — inline editor for a placed filter
// ---------------------------------------------------------------------------

function FilterRow({
  filter,
  onChange,
  onRemove,
}: {
  filter: SemanticFilter;
  onChange: (next: SemanticFilter) => void;
  onRemove: () => void;
}) {
  const valueless = VALUELESS_OPERATORS.includes(filter.operator);
  return (
    <div className="flex w-full flex-wrap items-center gap-1.5 rounded-md border bg-background/60 p-1.5">
      <span className="truncate text-xs font-medium" title={filter.member}>
        {filter.member}
      </span>
      <Select
        aria-label={`Operator for ${filter.member}`}
        value={filter.operator}
        onChange={(e) =>
          onChange({ ...filter, operator: e.target.value as SemanticFilterOperator, values: [] })
        }
        className="h-7 w-28 text-xs"
      >
        {FILTER_OPERATORS.map((op) => (
          <option key={op} value={op}>
            {op}
          </option>
        ))}
      </Select>
      {!valueless && (
        <input
          aria-label={`Values for ${filter.member}`}
          defaultValue={filter.values.join(", ")}
          onBlur={(e) => onChange({ ...filter, values: parseFilterValues(e.target.value) })}
          placeholder="value(s), comma-separated"
          className="h-7 flex-1 rounded border bg-transparent px-2 text-xs"
        />
      )}
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Remove filter ${filter.member}`}
        className="rounded p-0.5 text-muted-foreground hover:text-destructive"
      >
        <X className="h-3 w-3" />
      </button>
    </div>
  );
}
