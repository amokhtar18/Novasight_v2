import { describe, it, expect } from "vitest";
import { nodesToLayoutTiles } from "@/lib/dashboardLayout";

describe("nodesToLayoutTiles", () => {
  it("maps gridstack nodes to TileLayout with row-major position (y then x)", () => {
    // Out of visual order on purpose: bottom-left, top-right, top-left.
    const tiles = nodesToLayoutTiles([
      { id: "c", x: 0, y: 4, w: 6, h: 4 },
      { id: "b", x: 6, y: 0, w: 6, h: 4 },
      { id: "a", x: 0, y: 0, w: 6, h: 4 },
    ]);
    expect(tiles.map((t) => t.id)).toEqual(["a", "b", "c"]); // (0,0),(6,0),(0,4)
    expect(tiles.map((t) => t.position)).toEqual([0, 1, 2]);
    expect(tiles[0]).toEqual({ id: "a", position: 0, x: 0, y: 0, w: 6, h: 4 });
  });

  it("defaults missing geometry and drops nodes without a string id", () => {
    const tiles = nodesToLayoutTiles([
      { id: "a" },
      { id: undefined, x: 1, y: 1 },
      { x: 2, y: 2 },
    ]);
    expect(tiles).toEqual([{ id: "a", position: 0, x: 0, y: 0, w: 1, h: 1 }]);
  });
});
