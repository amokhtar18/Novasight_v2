/**
 * DashboardGrid — responsive grid of chart tiles with dnd-kit reordering.
 *
 * In edit mode, tiles can be dragged (pointer or keyboard) to reorder; the new
 * order is applied optimistically to the query cache and persisted via the layout
 * endpoint. Tile width (w, on the 12-col grid) maps to a column span at lg.
 */

import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  rectSortingStrategy,
  sortableKeyboardCoordinates,
} from "@dnd-kit/sortable";
import { useQueryClient } from "@tanstack/react-query";

import { queryKeys, useSetDashboardLayout } from "@/api/hooks";
import { DashboardCardTile } from "./DashboardCardTile";
import type { FilterSelections } from "@/lib/dashboardFilters";
import type { DashboardRead, DashboardTileRead, NativeFilter, SemanticFilter, SelectionPair } from "@/types/api";

interface DashboardGridProps {
  tiles: DashboardTileRead[];
  dashboardId: string;
  editing: boolean;
  /** Persisted native-filter configs for the dashboard. */
  filters: NativeFilter[];
  /** Live per-filter selections (session state). */
  selections: FilterSelections;
  /** Transient cross-filter session overlays; empty list while editing. */
  crossFilter: SemanticFilter[];
  /** Cross-filtering: set from a clicked chart point. */
  onCrossFilter?: (pairs: SelectionPair[]) => void;
}

export function DashboardGrid({
  tiles,
  dashboardId,
  editing,
  filters,
  selections,
  crossFilter,
  onCrossFilter,
}: DashboardGridProps) {
  const queryClient = useQueryClient();
  const setLayout = useSetDashboardLayout(dashboardId);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = tiles.findIndex((t) => t.id === active.id);
    const newIndex = tiles.findIndex((t) => t.id === over.id);
    if (oldIndex === -1 || newIndex === -1) return;

    const reordered = arrayMove(tiles, oldIndex, newIndex).map((t, i) => ({
      ...t,
      position: i,
    }));

    // Apply immediately to the cache so the grid doesn't snap back before the
    // mutation resolves; then persist the new order/sizes.
    queryClient.setQueryData<DashboardRead>(queryKeys.dashboard(dashboardId), (old) =>
      old ? { ...old, tiles: reordered } : old
    );
    setLayout.mutate({
      tiles: reordered.map((t) => ({
        id: t.id,
        position: t.position,
        x: t.x,
        y: t.y,
        w: t.w,
        h: t.h,
      })),
    });
  }

  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
      <SortableContext items={tiles.map((t) => t.id)} strategy={rectSortingStrategy}>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4 [grid-auto-flow:dense]">
          {tiles.map((tile) => (
            <DashboardCardTile
              key={tile.id}
              tile={tile}
              dashboardId={dashboardId}
              editing={editing}
              filters={filters}
              selections={selections}
              crossFilter={crossFilter}
              onCrossFilter={onCrossFilter}
            />
          ))}
        </div>
      </SortableContext>
    </DndContext>
  );
}
