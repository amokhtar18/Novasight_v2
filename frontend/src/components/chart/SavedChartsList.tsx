/**
 * SavedChartsList — the tenant's saved charts shown in the builder as a list (not tiles).
 *
 * Each row is one saved chart with its name, type, source model, and last-updated time,
 * plus actions: load it back into the builder shelves (onEdit), pin it to a dashboard, or
 * delete it. Kept intentionally compact (a list, not a preview grid) so it sits beside the
 * builder without competing with the live preview.
 */

import { useState } from "react";
import { BarChart3, Pencil, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { useCharts, useDeleteChart } from "@/api/hooks";
import { useIdentity } from "@/lib/identity";
import { AddToDashboard } from "@/components/dashboard/AddToDashboard";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Spinner } from "@/components/ui/spinner";
import { EmptyState } from "@/components/ui/empty-state";
import {
  Dialog,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { formatRelativeTime, humanize } from "@/lib/format";
import type { ChartSpec, SavedChartRead } from "@/types/api";

export function SavedChartsList({ onEdit }: { onEdit: (spec: ChartSpec) => void }) {
  const { data: charts, isLoading } = useCharts();
  const { canEdit } = useIdentity();
  const deleteChart = useDeleteChart();
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);

  function handleDelete(id: string) {
    deleteChart.mutate(id, {
      onError: (err) =>
        toast.error(err instanceof Error ? err.message : "Could not delete the chart"),
    });
    setPendingDelete(null);
  }

  return (
    <Card className="bg-card/70">
      <CardHeader>
        <CardTitle className="text-base">Saved charts</CardTitle>
        <CardDescription>
          Load one back into the builder to tweak it, pin it to a dashboard, or remove it.
        </CardDescription>
      </CardHeader>
      <div className="px-6 pb-6">
        {isLoading ? (
          <div className="flex h-24 items-center justify-center">
            <Spinner label="Loading charts" />
          </div>
        ) : !charts || charts.length === 0 ? (
          <EmptyState
            icon={<BarChart3 className="h-6 w-6" />}
            title="No saved charts yet"
            description="Build a chart above and save it to see it listed here."
          />
        ) : (
          <ul className="divide-y rounded-lg border">
            {charts.map((c) => (
              <ChartRow
                key={c.id}
                chart={c}
                canEdit={canEdit}
                onEdit={() => onEdit(c.spec)}
                onDelete={() => setPendingDelete(c.id)}
              />
            ))}
          </ul>
        )}
      </div>

      <Dialog
        open={pendingDelete !== null}
        onOpenChange={(o) => !o && setPendingDelete(null)}
        title="Delete chart"
      >
        <DialogHeader>
          <DialogTitle>Delete chart?</DialogTitle>
          <DialogDescription>
            This removes the saved chart. Dashboards that pinned it will lose the tile.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setPendingDelete(null)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={() => pendingDelete && handleDelete(pendingDelete)}
          >
            Delete
          </Button>
        </DialogFooter>
      </Dialog>
    </Card>
  );
}

function ChartRow({
  chart,
  canEdit,
  onEdit,
  onDelete,
}: {
  chart: SavedChartRead;
  canEdit: boolean;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const title = chart.spec.options?.title ?? chart.name;
  return (
    <li className="flex items-center gap-3 px-3 py-2">
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{chart.name}</p>
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          <Badge variant="secondary">{humanize(chart.spec.type)}</Badge>
          {chart.source_ref && (
            <Badge variant="info" className="max-w-[10rem] truncate">
              {chart.source_ref}
            </Badge>
          )}
          <span className="text-[0.7rem] text-muted-foreground">
            Updated {formatRelativeTime(chart.updated_at)}
          </span>
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-1">
        {canEdit && (
          <Button variant="ghost" size="sm" onClick={onEdit}>
            <Pencil className="h-4 w-4" aria-hidden />
            Load
          </Button>
        )}
        <AddToDashboard spec={chart.spec} title={title} />
        {canEdit && (
          <button
            type="button"
            onClick={onDelete}
            aria-label={`Delete ${chart.name}`}
            className="rounded-md p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        )}
      </div>
    </li>
  );
}
