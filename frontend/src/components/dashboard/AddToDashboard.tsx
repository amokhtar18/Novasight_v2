/**
 * AddToDashboard — a button that pins a ChartSpec onto a (server-side) dashboard.
 *
 * Opens a dialog to pick an existing dashboard or create a new one, then: saves the
 * chart (POST /charts) and pins it as a tile (POST /dashboards/{id}/tiles). The tile
 * stores no data — it re-runs the chart's grounded query when displayed. Used by the
 * Builder, Explore, and dataset Suggestions surfaces — anywhere a user produces a
 * chart worth keeping.
 */

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { LayoutDashboard, Plus } from "lucide-react";
import { toast } from "sonner";

import { useAddDashboardTile, useCreateChart, useCreateDashboard, useDashboards } from "@/api/hooks";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import {
  Dialog,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { ButtonProps } from "@/components/ui/button";
import type { ChartSourceKind, ChartSpec, QueryResponse } from "@/types/api";

interface AddToDashboardProps {
  spec: ChartSpec;
  title: string;
  /** Accepted for call-site compatibility; tiles re-run the spec, so it's unused. */
  data?: QueryResponse;
  variant?: ButtonProps["variant"];
  size?: ButtonProps["size"];
  className?: string;
}

const NEW = "__new__";

/** Derive where a spec reads its data, so the saved chart records its source. */
function deriveSource(spec: ChartSpec): { kind: ChartSourceKind; ref: string | null } {
  const metricRefs = spec.query.metric_refs ?? [];
  if (metricRefs.length > 0) {
    return { kind: "semantic", ref: metricRefs[0]?.split(".")[0] ?? null };
  }
  return { kind: "dataset", ref: spec.query.dataset_id ?? null };
}

export function AddToDashboard({
  spec,
  title,
  variant = "outline",
  size = "sm",
  className,
}: AddToDashboardProps) {
  const navigate = useNavigate();
  const { data: boards = [] } = useDashboards();
  const createChart = useCreateChart();
  const createDashboard = useCreateDashboard();
  const addTile = useAddDashboardTile();

  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState<string>(NEW);
  const [newName, setNewName] = useState("");

  const creating = target === NEW || boards.length === 0;
  const pending = createChart.isPending || createDashboard.isPending || addTile.isPending;

  async function handleSave() {
    try {
      const source = deriveSource(spec);
      const chart = await createChart.mutateAsync({
        name: title,
        spec,
        source_kind: source.kind,
        source_ref: source.ref,
      });

      let dashboardId = target;
      let dashboardName: string;
      if (creating) {
        const board = await createDashboard.mutateAsync({ name: newName || "My dashboard" });
        dashboardId = board.id;
        dashboardName = board.name;
      } else {
        dashboardName = boards.find((b) => b.id === dashboardId)?.name ?? "dashboard";
      }

      await addTile.mutateAsync({ dashboardId, tile: { chart_id: chart.id, title } });

      setOpen(false);
      setNewName("");
      toast.success(`Added to “${dashboardName}”`, {
        action: { label: "Open", onClick: () => navigate(`/dashboards/${dashboardId}`) },
      });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not add to dashboard");
    }
  }

  return (
    <>
      <Button
        type="button"
        variant={variant}
        size={size}
        className={className}
        onClick={() => setOpen(true)}
      >
        <LayoutDashboard className="h-4 w-4" aria-hidden />
        Add to dashboard
      </Button>

      <Dialog open={open} onOpenChange={setOpen} title="Add to dashboard">
        <DialogHeader>
          <DialogTitle>Add to dashboard</DialogTitle>
          <DialogDescription>
            Pin “{title}” to a dashboard. The chart is saved and re-runs its query when shown.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {boards.length > 0 && (
            <div className="space-y-1.5">
              <Label htmlFor="dash-target">Dashboard</Label>
              <Select id="dash-target" value={target} onChange={(e) => setTarget(e.target.value)}>
                {boards.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
                <option value={NEW}>+ Create new dashboard…</option>
              </Select>
            </div>
          )}

          {creating && (
            <div className="space-y-1.5">
              <Label htmlFor="dash-name">New dashboard name</Label>
              <Input
                id="dash-name"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="e.g. Sales overview"
                autoFocus
              />
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={pending}>
            <Plus className="h-4 w-4" aria-hidden />
            {pending ? "Saving…" : "Save"}
          </Button>
        </DialogFooter>
      </Dialog>
    </>
  );
}
