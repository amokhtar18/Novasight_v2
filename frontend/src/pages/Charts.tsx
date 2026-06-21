/**
 * Charts — the tenant's saved charts, with details and actions (#9).
 *
 * Lists every server-saved chart (name, type, source model, updated), with a live
 * preview that re-runs the chart's grounded query, plus pin-to-dashboard and delete.
 * Charts are built in the Chart builder; this is the library view of them.
 */

import { useState } from "react";
import { Link } from "react-router-dom";
import { BarChart3, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { useCharts, useDeleteChart } from "@/api/hooks";
import { useChartData } from "@/lib/useChartData";
import { useIdentity } from "@/lib/identity";
import { PageHeader } from "@/components/layout/PageHeader";
import { ChartRenderer } from "@/components/chart/ChartRenderer";
import { AddToDashboard } from "@/components/dashboard/AddToDashboard";
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
import type { SavedChartRead } from "@/types/api";

export function Charts() {
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
    <div className="animate-in-up">
      <PageHeader
        title="Charts"
        description="Your saved charts. Preview them, pin them to a dashboard, or remove them."
        actions={
          <Button asChild>
            <Link to="/build">
              <Plus className="h-4 w-4" aria-hidden />
              New chart
            </Link>
          </Button>
        }
      />

      {isLoading ? (
        <div className="flex h-48 items-center justify-center">
          <Spinner label="Loading charts" />
        </div>
      ) : !charts || charts.length === 0 ? (
        <EmptyState
          icon={<BarChart3 className="h-6 w-6" />}
          title="No saved charts yet"
          description="Build a chart in the chart builder and save it to see it here."
          action={
            <Button asChild>
              <Link to="/build">
                <Plus className="h-4 w-4" aria-hidden />
                Open builder
              </Link>
            </Button>
          }
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {charts.map((c) => (
            <ChartCard
              key={c.id}
              chart={c}
              canEdit={canEdit}
              onDelete={() => setPendingDelete(c.id)}
            />
          ))}
        </div>
      )}

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
          <Button variant="destructive" onClick={() => pendingDelete && handleDelete(pendingDelete)}>
            Delete
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}

function ChartCard({
  chart,
  canEdit,
  onDelete,
}: {
  chart: SavedChartRead;
  canEdit: boolean;
  onDelete: () => void;
}) {
  const { data, isLoading, isError } = useChartData(chart.spec);
  const title = chart.spec.options?.title ?? chart.name;

  return (
    <div className="group relative flex flex-col rounded-xl border bg-card/70 p-4 transition-colors hover:border-primary/50">
      <div className="mb-3 h-40">
        {isLoading ? (
          <div className="flex h-full items-center justify-center">
            <Spinner label="Loading preview" />
          </div>
        ) : isError || !data || data.row_count === 0 ? (
          <div className="flex h-full items-center justify-center rounded-lg bg-background/40 text-xs text-muted-foreground">
            Preview unavailable
          </div>
        ) : (
          <ChartRenderer spec={chart.spec} data={data} title={title} className="h-40" />
        )}
      </div>

      <p className="truncate text-sm font-medium">{chart.name}</p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Badge variant="secondary">{humanize(chart.spec.type)}</Badge>
        {chart.source_ref && (
          <Badge variant="info" className="max-w-[10rem] truncate">
            {chart.source_ref}
          </Badge>
        )}
      </div>
      <p className="mt-2 text-[0.7rem] text-muted-foreground">
        Updated {formatRelativeTime(chart.updated_at)}
      </p>

      <div className="mt-3 flex items-center gap-2">
        <AddToDashboard spec={chart.spec} title={title} />
        {canEdit && (
          <button
            type="button"
            onClick={onDelete}
            aria-label={`Delete ${chart.name}`}
            className="ml-auto rounded-md p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        )}
      </div>
    </div>
  );
}
