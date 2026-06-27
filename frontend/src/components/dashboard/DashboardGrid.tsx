/**
 * DashboardGrid — a free 12-column resizable grid of tiles (gridstack).
 *
 * React renders the `.grid-stack` items (carrying the tile's gs-x/y/w/h) and a
 * `useEffect` initializes gridstack, which adopts them as draggable/resizable
 * widgets. Tile content stays ordinary React. On a layout change gridstack's
 * geometry is mapped to the existing `PUT /dashboards/{id}/layout` payload
 * (debounced + optimistic). Drag/resize are enabled only in edit mode.
 */

import { useEffect, useRef, type HTMLAttributes } from "react";
import { GridStack } from "gridstack";

import { useQueryClient } from "@tanstack/react-query";

import { queryKeys, useSetDashboardLayout } from "@/api/hooks";
import { DashboardCardTile } from "./DashboardCardTile";
import { nodesToLayoutTiles, type GridLayoutNode } from "@/lib/dashboardLayout";
import type { FilterSelections } from "@/lib/dashboardFilters";
import type {
  DashboardRead,
  DashboardTileRead,
  NativeFilter,
  SemanticFilter,
  SelectionPair,
} from "@/types/api";

const GRID_COLUMNS = 12;
const GRID_CELL_HEIGHT = 64; // px per row unit
const GRID_MARGIN = 8; // px gutter
const GRID_MOBILE_BREAKPOINT = 768; // collapse to one column below this width
const SAVE_DEBOUNCE_MS = 400;

interface DashboardGridProps {
  tiles: DashboardTileRead[];
  dashboardId: string;
  editing: boolean;
  filters: NativeFilter[];
  selections: FilterSelections;
  crossFilter: SemanticFilter[];
  onCrossFilter?: (pairs: SelectionPair[]) => void;
}

/** gridstack reads geometry from these attributes when it adopts the DOM items. */
function gsItemAttrs(tile: DashboardTileRead) {
  return {
    "gs-id": tile.id,
    "gs-x": tile.x,
    "gs-y": tile.y,
    "gs-w": tile.w,
    "gs-h": tile.h,
  } as unknown as HTMLAttributes<HTMLDivElement>;
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
  const elRef = useRef<HTMLDivElement>(null);
  const gridRef = useRef<GridStack | null>(null);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Re-init gridstack only when the tile SET changes (add/remove) — not on
  // drag/resize or data refresh. A changing key would remount; instead we key
  // the effect on the joined ids.
  const tileIds = tiles.map((t) => t.id).join(",");

  // The once-bound change handler reads current values through this ref.
  // We update the ref inside an effect to satisfy the react-hooks/refs lint rule
  // (refs must not be written during render).
  const persistRef = useRef<() => void>(() => {});
  useEffect(() => {
    persistRef.current = () => {
      const grid = gridRef.current;
      if (!grid) return;
      const layoutTiles = nodesToLayoutTiles(grid.save(false) as GridLayoutNode[]);
      queryClient.setQueryData<DashboardRead>(queryKeys.dashboard(dashboardId), (old) => {
        if (!old) return old;
        const byId = new Map(layoutTiles.map((l) => [l.id, l]));
        return {
          ...old,
          tiles: old.tiles.map((t) => {
            const l = byId.get(t.id);
            return l
              ? { ...t, position: l.position, x: l.x ?? t.x, y: l.y ?? t.y, w: l.w ?? t.w, h: l.h ?? t.h }
              : t;
          }),
        };
      });
      setLayout.mutate({ tiles: layoutTiles });
    };
  });

  /** Resize one tile through gridstack (the keyboard a11y control calls this in Task 3). */
  function resizeTile(tileId: string, w: number, h: number) {
    const grid = gridRef.current;
    const el = elRef.current?.querySelector<HTMLElement>(`[gs-id="${CSS.escape(tileId)}"]`);
    if (grid && el) grid.update(el, { w, h }); // fires "change" → debounced persist
  }

  useEffect(() => {
    if (!elRef.current) return;
    const grid = GridStack.init(
      {
        column: GRID_COLUMNS,
        cellHeight: GRID_CELL_HEIGHT,
        margin: GRID_MARGIN,
        float: false,
        handle: ".tile-drag-handle",
        disableDrag: !editing,
        disableResize: !editing,
        columnOpts: { breakpoints: [{ w: GRID_MOBILE_BREAKPOINT, c: 1 }], breakpointForWindow: true },
      },
      elRef.current
    );
    gridRef.current = grid;
    grid.on("change", () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
      saveTimer.current = setTimeout(() => persistRef.current(), SAVE_DEBOUNCE_MS);
    });
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
      grid.off("change");
      grid.destroy(false);
      gridRef.current = null;
    };
    // Re-init only when the tile set changes; `editing` is synced by the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tileIds]);

  // Toggle drag/resize on edit-mode change without re-initializing.
  useEffect(() => {
    const grid = gridRef.current;
    if (!grid) return;
    grid.enableMove(editing);
    grid.enableResize(editing);
  }, [editing]);

  return (
    <div ref={elRef} className="grid-stack">
      {tiles.map((tile) => (
        <div key={tile.id} className="grid-stack-item" {...gsItemAttrs(tile)}>
          <div className="grid-stack-item-content">
            <DashboardCardTile
              tile={tile}
              dashboardId={dashboardId}
              editing={editing}
              filters={filters}
              selections={selections}
              crossFilter={crossFilter}
              onCrossFilter={onCrossFilter}
              onResizeTile={resizeTile}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
