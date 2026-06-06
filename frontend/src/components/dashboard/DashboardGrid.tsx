/**
 * DashboardGrid — responsive grid of chart tiles with dnd-kit reordering.
 *
 * In edit mode, tiles can be dragged (pointer or keyboard) to reorder; the new
 * order is persisted to the dashboards store. Tile width (sm/md/lg) maps to a
 * column span on the lg breakpoint.
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

import { useDashboardsStore, type DashboardItem } from "@/store/dashboardsStore";
import { DashboardCardTile } from "./DashboardCardTile";

interface DashboardGridProps {
  items: DashboardItem[];
  tenantId: string;
  dashboardId: string;
  editing: boolean;
}

export function DashboardGrid({
  items,
  tenantId,
  dashboardId,
  editing,
}: DashboardGridProps) {
  const setItems = useDashboardsStore((s) => s.setItems);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = items.findIndex((i) => i.id === active.id);
    const newIndex = items.findIndex((i) => i.id === over.id);
    if (oldIndex === -1 || newIndex === -1) return;
    setItems(tenantId, dashboardId, arrayMove(items, oldIndex, newIndex));
  }

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragEnd={handleDragEnd}
    >
      <SortableContext items={items.map((i) => i.id)} strategy={rectSortingStrategy}>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4 [grid-auto-flow:dense]">
          {items.map((item) => (
            <DashboardCardTile
              key={item.id}
              item={item}
              tenantId={tenantId}
              dashboardId={dashboardId}
              editing={editing}
            />
          ))}
        </div>
      </SortableContext>
    </DndContext>
  );
}
