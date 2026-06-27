/**
 * DashboardCardTile — one placed object on a dashboard (#10).
 *
 * A tile is a `kind`: a pinned `chart` (re-runs its grounded query via useChartData so
 * it always shows current data) or a decoration — `text`, `markdown`, `image`, or
 * `divider`. In edit mode every tile exposes a drag handle (gridstack), a keyboard-accessible size control, and a remove button.
 *
 * Native filters (Slice C): chart tiles resolve their applicable filters via
 * `resolveTileFilters` and pass them + any date-range overrides to `useChartData`.
 * A transient cross-filter overlay is applied on top when its cube matches the tile.
 */

import { useRef, useState } from "react";
import { GripVertical, Trash2 } from "lucide-react";

import { TileSizeControl } from "./TileSizeControl";
import { ChartRenderer, type ChartRendererHandle } from "@/components/chart/ChartRenderer";
import { ChartActionsMenu } from "@/components/chart/ChartActionsMenu";
import { DrillByModal } from "@/components/chart/DrillByModal";
import { DrillToDetailModal } from "@/components/chart/DrillToDetailModal";
import { EmptyState } from "@/components/ui/empty-state";
import { Badge } from "@/components/ui/badge";
import { useDeleteDashboardTile } from "@/api/hooks";
import { useChartData } from "@/lib/useChartData";
import { renderMarkdown } from "@/lib/markdown";
import { resolveTileFilters, cubeOf } from "@/lib/dashboardFilters";
import type { FilterSelections } from "@/lib/dashboardFilters";
import type { DashboardTileRead, NativeFilter, SemanticFilter, SelectionPair } from "@/types/api";

const KIND_LABEL: Record<string, string> = {
  text: "Text",
  markdown: "Note",
  image: "Image",
  divider: "Divider",
};

interface TileProps {
  tile: DashboardTileRead;
  dashboardId: string;
  editing: boolean;
  /** Persisted native-filter configs for the dashboard. */
  filters?: NativeFilter[];
  /** Live per-filter selections (session state). */
  selections?: FilterSelections;
  /** Transient cross-filter session overlays (empty list = no overlay). */
  crossFilter?: SemanticFilter[];
  onCrossFilter?: (pairs: SelectionPair[]) => void;
  onResizeTile?: (tileId: string, w: number, h: number) => void;
}

export function DashboardCardTile({
  tile,
  dashboardId,
  editing,
  filters = [],
  selections = {},
  crossFilter = [],
  onCrossFilter,
  onResizeTile,
}: TileProps) {
  const deleteTile = useDeleteDashboardTile(dashboardId);

  const title =
    tile.title ?? (tile.kind === "chart" ? tile.chart?.name ?? "Chart" : KIND_LABEL[tile.kind] ?? "Tile");

  return (
    <div className="group/tile flex h-full flex-col rounded-xl border bg-card/70 p-4 shadow-[var(--elevation-1)] transition-shadow hover:shadow-[var(--elevation-3)]">
      <div className="mb-2 flex items-center gap-2">
        {editing && (
          <button
            type="button"
            className="tile-drag-handle cursor-grab touch-none rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground active:cursor-grabbing"
            aria-label={`Drag ${title}`}
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
            <TileSizeControl
              title={title}
              w={tile.w}
              h={tile.h}
              onResize={(w, h) => onResizeTile?.(tile.id, w, h)}
            />
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
          filters={filters}
          selections={selections}
          crossFilter={crossFilter}
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
  filters,
  selections,
  crossFilter,
  onCrossFilter,
  title,
}: {
  tile: DashboardTileRead;
  editing: boolean;
  filters: NativeFilter[];
  selections: FilterSelections;
  crossFilter: SemanticFilter[];
  onCrossFilter?: (pairs: SelectionPair[]) => void;
  title: string;
}) {
  const content = tile.content ?? {};

  switch (tile.kind) {
    case "chart":
      return (
        <ChartTileBody
          tile={tile}
          editing={editing}
          filters={filters}
          selections={selections}
          crossFilter={crossFilter}
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
    default:
      return null;
  }
}

function ChartTileBody({
  tile,
  editing,
  filters,
  selections,
  crossFilter,
  onCrossFilter,
  title,
}: {
  tile: DashboardTileRead;
  editing: boolean;
  filters: NativeFilter[];
  selections: FilterSelections;
  crossFilter: SemanticFilter[];
  onCrossFilter?: (pairs: SelectionPair[]) => void;
  title: string;
}) {
  const spec = tile.chart?.spec;

  const [drillBy, setDrillBy] = useState(false);
  const [drillDetail, setDrillDetail] = useState(false);
  const isSemantic = (spec?.query.metric_refs ?? []).length > 0;

  const { filters: resolved, dateRanges } = resolveTileFilters(filters, selections, tile);
  const tileCube = cubeOf((spec?.query.metric_refs ?? [])[0]);
  const crossMatching = crossFilter.filter((cf) => !!tileCube && cubeOf(cf.member) === tileCube);
  const appliedFilters: SemanticFilter[] = [...resolved, ...crossMatching];
  const hasOverride = Object.keys(dateRanges).length > 0;

  const { data, isLoading, isError } = useChartData(
    spec ?? null,
    appliedFilters.length > 0 ? appliedFilters : undefined,
    hasOverride ? dateRanges : undefined
  );
  const filterApplies = appliedFilters.length > 0 || hasOverride;

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
        <div className="h-56 w-full animate-pulse rounded-md bg-muted/50" />
      ) : data && data.row_count > 0 ? (
        <div className="relative h-full">
          {!editing && (
            <div className="absolute right-0 top-0 z-10">
              <ChartActionsMenu
                spec={spec} data={data} chartHandle={chartHandle} title={title}
                onDrillBy={isSemantic ? () => setDrillBy(true) : undefined}
                onDrillToDetail={isSemantic ? () => setDrillDetail(true) : undefined}
              />
            </div>
          )}
          <ChartRenderer
            ref={chartHandle}
            spec={spec}
            data={data}
            title={title}
            className="h-full"
            onSelectPoints={editing ? undefined : onCrossFilter}
          />
        </div>
      ) : isError ? (
        <EmptyState title="Couldn't load data" description="This tile's query failed to run." />
      ) : (
        <EmptyState title="No data" description="This chart returned no rows." />
      )}
      {drillBy && data && (
        <DrillByModal open={drillBy} onOpenChange={setDrillBy} spec={spec} tileFilters={appliedFilters} data={data} />
      )}
      {drillDetail && data && (
        <DrillToDetailModal open={drillDetail} onOpenChange={setDrillDetail} spec={spec} tileFilters={appliedFilters} data={data} />
      )}
    </>
  );
}
