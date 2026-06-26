/**
 * DashboardCardTile — one placed object on a dashboard (#10).
 *
 * A tile is a `kind`: a pinned `chart` (re-runs its grounded query via useChartData so
 * it always shows current data) or a decoration — `text`, `markdown`, `image`,
 * `divider`, or `filter` (a slicer that drives the dashboard's view-time filter). In
 * edit mode every tile exposes a drag handle (dnd-kit), a size control, and remove.
 */

import { useRef, useState } from "react";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, Trash2 } from "lucide-react";

import { ChartRenderer, type ChartRendererHandle } from "@/components/chart/ChartRenderer";
import { ChartActionsMenu } from "@/components/chart/ChartActionsMenu";
import { Spinner } from "@/components/ui/spinner";
import { EmptyState } from "@/components/ui/empty-state";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { useDeleteDashboardTile, useUpdateDashboardTile } from "@/api/hooks";
import { useChartData } from "@/lib/useChartData";
import { renderMarkdown } from "@/lib/markdown";
import { cn } from "@/lib/cn";
import type { DashboardTileRead, SemanticFilter } from "@/types/api";

type TileSize = "sm" | "md" | "lg";

const SIZE_TO_W: Record<TileSize, number> = { sm: 3, md: 6, lg: 12 };

function sizeFromW(w: number): TileSize {
  if (w >= 12) return "lg";
  if (w >= 6) return "md";
  return "sm";
}

function spanForW(w: number): string {
  if (w >= 12) return "lg:col-span-4";
  if (w >= 6) return "lg:col-span-2";
  return "lg:col-span-1";
}

const KIND_LABEL: Record<string, string> = {
  text: "Text",
  markdown: "Note",
  image: "Image",
  divider: "Divider",
  filter: "Filter",
};

interface TileProps {
  tile: DashboardTileRead;
  dashboardId: string;
  editing: boolean;
  activeFilter?: SemanticFilter | null;
  onCrossFilter?: (member: string, value: string) => void;
}

export function DashboardCardTile({
  tile,
  dashboardId,
  editing,
  activeFilter,
  onCrossFilter,
}: TileProps) {
  const updateTile = useUpdateDashboardTile(dashboardId);
  const deleteTile = useDeleteDashboardTile(dashboardId);

  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: tile.id,
    disabled: !editing,
  });

  const title =
    tile.title ?? (tile.kind === "chart" ? tile.chart?.name ?? "Chart" : KIND_LABEL[tile.kind] ?? "Tile");

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    zIndex: isDragging ? 20 : undefined,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={cn(
        "flex flex-col rounded-xl border bg-card/70 p-4 shadow-sm",
        spanForW(tile.w),
        isDragging && "opacity-70 ring-2 ring-primary"
      )}
    >
      <div className="mb-2 flex items-center gap-2">
        {editing && (
          <button
            type="button"
            className="cursor-grab touch-none rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground active:cursor-grabbing"
            aria-label={`Drag ${title}`}
            {...attributes}
            {...listeners}
          >
            <GripVertical className="h-4 w-4" />
          </button>
        )}
        {tile.kind !== "divider" && (
          <h3 className="min-w-0 flex-1 truncate text-sm font-medium" title={title}>
            {title}
          </h3>
        )}
        {tile.kind === "divider" && <span className="flex-1" />}
        {editing && (
          <>
            <Select
              aria-label={`Size of ${title}`}
              value={sizeFromW(tile.w)}
              onChange={(e) =>
                updateTile.mutate({
                  tileId: tile.id,
                  patch: { w: SIZE_TO_W[e.target.value as TileSize] },
                })
              }
              className="h-7 w-20 text-xs"
            >
              <option value="sm">Small</option>
              <option value="md">Medium</option>
              <option value="lg">Large</option>
            </Select>
            <button
              type="button"
              onClick={() => deleteTile.mutate(tile.id)}
              aria-label={`Remove ${title}`}
              className="rounded p-1 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </>
        )}
      </div>

      <div className="min-h-[6rem] flex-1">
        <TileBody
          tile={tile}
          editing={editing}
          activeFilter={activeFilter}
          onCrossFilter={onCrossFilter}
          title={title}
        />
      </div>
    </div>
  );
}

function TileBody({
  tile,
  editing,
  activeFilter,
  onCrossFilter,
  title,
}: {
  tile: DashboardTileRead;
  editing: boolean;
  activeFilter?: SemanticFilter | null;
  onCrossFilter?: (member: string, value: string) => void;
  title: string;
}) {
  const content = tile.content ?? {};

  switch (tile.kind) {
    case "chart":
      return (
        <ChartTileBody
          tile={tile}
          editing={editing}
          activeFilter={activeFilter}
          onCrossFilter={onCrossFilter}
          title={title}
        />
      );
    case "text":
      return (
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">
          {String(content.text ?? "")}
        </p>
      );
    case "markdown":
      return (
        <div
          className="space-y-1 text-sm leading-relaxed [&_a]:text-primary [&_a]:underline [&_h1]:text-lg [&_h1]:font-semibold [&_h2]:font-semibold"
          // Safe: the source is HTML-escaped before a small allow-list is re-applied.
          dangerouslySetInnerHTML={{
            __html: renderMarkdown(String(content.markdown ?? content.text ?? "")),
          }}
        />
      );
    case "image": {
      const url = String(content.url ?? "");
      return url ? (
        <img
          src={url}
          alt={String(content.alt ?? title)}
          referrerPolicy="no-referrer"
          className="max-h-72 w-full rounded-md object-contain"
        />
      ) : (
        <EmptyState title="No image" description="This image tile has no URL." />
      );
    }
    case "divider":
      return (
        <div className="flex items-center gap-3 py-2">
          <hr className="flex-1 border-border" />
          {content.label ? (
            <span className="text-xs uppercase tracking-wide text-muted-foreground">
              {String(content.label)}
            </span>
          ) : null}
          <hr className="flex-1 border-border" />
        </div>
      );
    case "filter":
      return <FilterSlicer tile={tile} onCrossFilter={onCrossFilter} disabled={editing} />;
    default:
      return null;
  }
}

/** The cube a member belongs to (the part before the first dot), or undefined. */
function cubeOf(member: string | undefined): string | undefined {
  return member?.includes(".") ? member.split(".")[0] : undefined;
}

function ChartTileBody({
  tile,
  editing,
  activeFilter,
  onCrossFilter,
  title,
}: {
  tile: DashboardTileRead;
  editing: boolean;
  activeFilter?: SemanticFilter | null;
  onCrossFilter?: (member: string, value: string) => void;
  title: string;
}) {
  const spec = tile.chart?.spec;

  // Apply the dashboard filter only to a semantic tile on the same cube.
  const tileCube = cubeOf((spec?.query.metric_refs ?? [])[0]);
  const filterApplies = !!activeFilter && !!tileCube && cubeOf(activeFilter.member) === tileCube;
  const appliedFilters = filterApplies ? [activeFilter as SemanticFilter] : undefined;

  const crossDimension = tileCube && spec?.encoding.x ? spec.encoding.x : undefined;
  const onSelectCategory =
    onCrossFilter && crossDimension
      ? (value: string) => onCrossFilter(crossDimension, value)
      : undefined;

  const { data, isLoading, isError } = useChartData(spec ?? null, appliedFilters);

  const chartHandle = useRef<ChartRendererHandle>(null);

  if (!spec) {
    return <EmptyState title="Chart unavailable" description="This chart was removed." />;
  }

  return (
    <>
      {filterApplies && !editing && (
        <Badge variant="info" className="mb-2 shrink-0">
          Filtered
        </Badge>
      )}
      {isLoading ? (
        <div className="flex h-56 items-center justify-center">
          <Spinner label="Loading chart" />
        </div>
      ) : data && data.row_count > 0 ? (
        <div className="relative h-full">
          {!editing && (
            <div className="absolute right-0 top-0 z-10">
              <ChartActionsMenu spec={spec} data={data} chartHandle={chartHandle} title={title} />
            </div>
          )}
          <ChartRenderer
            ref={chartHandle}
            spec={spec}
            data={data}
            title={title}
            className="h-64"
            onSelectCategory={editing ? undefined : onSelectCategory}
          />
        </div>
      ) : isError ? (
        <EmptyState title="Couldn't load data" description="This tile's query failed to run." />
      ) : (
        <EmptyState title="No data" description="This chart returned no rows." />
      )}
    </>
  );
}

function FilterSlicer({
  tile,
  onCrossFilter,
  disabled,
}: {
  tile: DashboardTileRead;
  onCrossFilter?: (member: string, value: string) => void;
  disabled: boolean;
}) {
  const member = String(tile.content?.member ?? "");
  const [value, setValue] = useState("");

  if (!member) {
    return <p className="text-xs text-muted-foreground">No filter member configured.</p>;
  }

  const apply = () => {
    if (onCrossFilter && value.trim()) onCrossFilter(member, value.trim());
  };

  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">Filter the dashboard by {member}</p>
      <Input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="value…"
        aria-label={`Filter ${member}`}
        disabled={disabled}
        onKeyDown={(e) => {
          if (e.key === "Enter") apply();
        }}
      />
      <Button size="sm" variant="outline" disabled={disabled || !value.trim()} onClick={apply}>
        Apply
      </Button>
    </div>
  );
}
