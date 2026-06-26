import type { TileLayout } from "@/types/api";

/** The geometry subset of a gridstack node/widget that we persist. */
export interface GridLayoutNode {
  id?: string | number | null;
  x?: number;
  y?: number;
  w?: number;
  h?: number;
}

/**
 * Map gridstack's saved nodes to the dashboard layout payload. `position` is
 * derived row-major (top-to-bottom, then left-to-right) so the server's
 * position-ordered reads stay coherent with the visual grid. Nodes without a
 * non-empty string id (the tile id we set via `gs-id`) are dropped.
 */
export function nodesToLayoutTiles(nodes: GridLayoutNode[]): TileLayout[] {
  return nodes
    .filter((n): n is GridLayoutNode & { id: string } => typeof n.id === "string" && n.id.length > 0)
    .slice()
    .sort((a, b) => (a.y ?? 0) - (b.y ?? 0) || (a.x ?? 0) - (b.x ?? 0))
    .map((n, i) => ({
      id: n.id,
      position: i,
      x: n.x ?? 0,
      y: n.y ?? 0,
      w: n.w ?? 1,
      h: n.h ?? 1,
    }));
}
