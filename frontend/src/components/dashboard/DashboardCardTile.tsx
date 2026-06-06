/**
 * DashboardCardTile — one chart tile on a dashboard.
 *
 * Renders a saved DashboardItem. If the spec is a re-runnable dataset query it
 * re-fetches live; otherwise it renders from the snapshot captured at save time.
 * In edit mode it exposes a drag handle (dnd-kit sortable), a size control, and
 * a remove action.
 */

import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, Trash2 } from "lucide-react";

import { ChartRenderer } from "@/components/chart/ChartRenderer";
import { Spinner } from "@/components/ui/spinner";
import { EmptyState } from "@/components/ui/empty-state";
import { Select } from "@/components/ui/select";
import { useDatasetQuery } from "@/api/hooks";
import { useDashboardsStore, type DashboardItem, type TileSize } from "@/store/dashboardsStore";
import { cn } from "@/lib/cn";
import type { QueryRequest } from "@/types/api";

const SPAN: Record<TileSize, string> = {
  sm: "lg:col-span-1",
  md: "lg:col-span-2",
  lg: "lg:col-span-4",
};

const EMPTY_QUERY: QueryRequest = { dimensions: [], metrics: [] };

interface TileProps {
  item: DashboardItem;
  tenantId: string;
  dashboardId: string;
  editing: boolean;
}

export function DashboardCardTile({
  item,
  tenantId,
  dashboardId,
  editing,
}: TileProps) {
  const removeItem = useDashboardsStore((s) => s.removeItem);
  const setItemSize = useDashboardsStore((s) => s.setItemSize);

  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: item.id, disabled: !editing });

  // Re-runnable when there's an inline dataset query and no captured snapshot.
  const reRunnable =
    !item.data && !!item.spec.query.dataset_id && !!item.spec.query.query;
  const datasetId = reRunnable ? item.spec.query.dataset_id! : null;
  const request = item.spec.query.query ?? EMPTY_QUERY;
  const { data: live, isLoading, isError } = useDatasetQuery(datasetId, request);

  const data = item.data ?? live;

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
        SPAN[item.size],
        isDragging && "opacity-70 ring-2 ring-primary"
      )}
    >
      <div className="mb-2 flex items-center gap-2">
        {editing && (
          <button
            type="button"
            className="cursor-grab touch-none rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground active:cursor-grabbing"
            aria-label={`Drag ${item.title}`}
            {...attributes}
            {...listeners}
          >
            <GripVertical className="h-4 w-4" />
          </button>
        )}
        <h3 className="min-w-0 flex-1 truncate text-sm font-medium" title={item.title}>
          {item.title}
        </h3>
        {editing && (
          <>
            <Select
              aria-label={`Size of ${item.title}`}
              value={item.size}
              onChange={(e) =>
                setItemSize(tenantId, dashboardId, item.id, e.target.value as TileSize)
              }
              className="h-7 w-20 text-xs"
            >
              <option value="sm">Small</option>
              <option value="md">Medium</option>
              <option value="lg">Large</option>
            </Select>
            <button
              type="button"
              onClick={() => removeItem(tenantId, dashboardId, item.id)}
              aria-label={`Remove ${item.title}`}
              className="rounded p-1 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </>
        )}
      </div>

      <div className="min-h-[14rem] flex-1">
        {isLoading && !data ? (
          <div className="flex h-56 items-center justify-center">
            <Spinner label="Loading chart" />
          </div>
        ) : data && data.row_count > 0 ? (
          <ChartRenderer spec={item.spec} data={data} title={item.title} className="h-64" />
        ) : isError ? (
          <EmptyState title="Couldn't load data" description="This tile's query failed to run." />
        ) : (
          <EmptyState title="No data" description="This chart returned no rows." />
        )}
      </div>
    </div>
  );
}
