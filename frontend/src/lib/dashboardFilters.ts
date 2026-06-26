/**
 * Native-filter resolution + scoping (Slice C).
 *
 * Native filters persist as configs on the dashboard; at view time their live
 * selections resolve to Slice-A primitives (SemanticFilter[] / a time date_range) and
 * are applied per-tile. A filter only touches a tile whose cube contains its member
 * (the safety invariant that keeps a filter from breaking an unrelated tile).
 */
import type {
  DashboardTileRead, NativeFilter, RelativeDateRange, SemanticFilter,
} from "@/types/api";

export type FilterSelection =
  | { kind: "value"; values: string[] }
  | { kind: "time"; date_range: RelativeDateRange | string[] | null }
  | { kind: "numeric"; min: number | null; max: number | null };

export type FilterSelections = Record<string, FilterSelection>;

/** The cube a fully-qualified member belongs to (the part before the first dot). */
export function cubeOf(member: string | undefined): string | undefined {
  return member?.includes(".") ? member.split(".")[0] : undefined;
}

/**
 * The cubes a chart tile reads. Derived from the spec's `metric_refs` only — every
 * tile has at least one metric, and a measure's cube is the tile's governing cube, so
 * this is sufficient for the cube-compatibility check without inspecting dimensions.
 */
function tileCubes(tile: DashboardTileRead): Set<string> {
  const cubes = new Set<string>();
  for (const m of tile.chart?.spec.query?.metric_refs ?? []) {
    const c = cubeOf(m);
    if (c) cubes.add(c);
  }
  return cubes;
}

/** The default live selection a filter's config seeds. */
export function defaultSelection(f: NativeFilter): FilterSelection {
  if (f.kind === "value") return { kind: "value", values: f.default_values ?? [] };
  if (f.kind === "time") return { kind: "time", date_range: f.date_range ?? null };
  return { kind: "numeric", min: f.numeric_range?.min ?? null, max: f.numeric_range?.max ?? null };
}

/**
 * Whether a filter applies to a tile. The cube-compatibility check ALWAYS holds, so a
 * filter can never break an unrelated tile. With tile-scope it must also be listed.
 */
export function filterAppliesToTile(f: NativeFilter, tile: DashboardTileRead): boolean {
  if (tile.kind !== "chart") return false;
  const cube = cubeOf(f.member);
  if (!cube || !tileCubes(tile).has(cube)) return false;
  const scope = f.scope ?? { mode: "auto", tile_ids: [] };
  if (scope.mode === "tiles") return scope.tile_ids.includes(tile.id);
  return true;
}

/** Resolve all applicable filters for one tile into Slice-A primitives. */
export function resolveTileFilters(
  filters: NativeFilter[],
  selections: FilterSelections,
  tile: DashboardTileRead,
): { filters: SemanticFilter[]; dateRanges: Record<string, RelativeDateRange | string[]> } {
  const out: SemanticFilter[] = [];
  const dateRanges: Record<string, RelativeDateRange | string[]> = {};
  for (const f of filters) {
    if (!filterAppliesToTile(f, tile)) continue;
    const sel = selections[f.id] ?? defaultSelection(f);
    if (sel.kind === "value" && sel.values.length > 0) {
      // `operator` is optional on the config; a value filter without one defaults to
      // `equals` (the editor's default), matching the backend's value-filter contract.
      out.push({ member: f.member, operator: f.operator ?? "equals", values: sel.values });
    } else if (sel.kind === "numeric") {
      if (sel.min !== null) out.push({ member: f.member, operator: "gte", values: [String(sel.min)] });
      if (sel.max !== null) out.push({ member: f.member, operator: "lte", values: [String(sel.max)] });
    } else if (sel.kind === "time" && sel.date_range) {
      dateRanges[f.member] = sel.date_range;
    }
  }
  return { filters: out, dateRanges };
}
