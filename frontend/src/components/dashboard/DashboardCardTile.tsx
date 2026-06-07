/**
 * DashboardCardTile — one chart tile on a dashboard.
 *
 * Renders a placed tile's saved chart. The tile stores no data — it re-runs the
 * chart's grounded query (semantic or dataset) via useChartData, so it always
 * shows current data. In edit mode it exposes a drag handle (dnd-kit sortable), a
 * size control, and a remove action.
 */

import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, Trash2 } from "lucide-react";

import { ChartRenderer } from "@/components/chart/ChartRenderer";
import { Spinner } from "@/components/ui/spinner";
import { EmptyState } from "@/components/ui/empty-state";
import { Select } from "@/components/ui/select";
import { useDeleteDashboardTile, useUpdateDashboardTile } from "@/api/hooks";
import { useChartData } from "@/lib/useChartData";
import { cn } from "@/lib/cn";
import type { DashboardTileRead } from "@/types/api";

type TileSize = "sm" | "md" | "lg";

// Tile width on the 12-col grid ↔ the lg column span used by this grid (4 cols).
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

interface TileProps {
  tile: DashboardTileRead;
  dashboardId: string;
  editing: boolean;
}

export function DashboardCardTile({ tile, dashboardId, editing }: TileProps) {
  const updateTile = useUpdateDashboardTile(dashboardId);
  const deleteTile = useDeleteDashboardTile(dashboardId);

  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: tile.id,
    disabled: !editing,
  });

  const spec = tile.chart.spec;
  const title = tile.title ?? tile.chart.name;
  const { data, isLoading, isError } = useChartData(spec);

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
        <h3 className="min-w-0 flex-1 truncate text-sm font-medium" title={title}>
          {title}
        </h3>
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

      <div className="min-h-[14rem] flex-1">
        {isLoading ? (
          <div className="flex h-56 items-center justify-center">
            <Spinner label="Loading chart" />
          </div>
        ) : data && data.row_count > 0 ? (
          <ChartRenderer spec={spec} data={data} title={title} className="h-64" />
        ) : isError ? (
          <EmptyState title="Couldn't load data" description="This tile's query failed to run." />
        ) : (
          <EmptyState title="No data" description="This chart returned no rows." />
        )}
      </div>
    </div>
  );
}
