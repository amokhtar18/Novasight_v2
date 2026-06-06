/**
 * AddToDashboard — a button that saves a ChartSpec onto a dashboard.
 *
 * Opens a dialog to pick an existing dashboard or create a new one, then pins
 * the chart (spec + title) as a tile. Persistence is client-side (per tenant)
 * via the dashboards store. Used by the Builder, Explore, and dataset
 * Suggestions surfaces — anywhere a user produces a chart worth keeping.
 */

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { LayoutDashboard, Plus } from "lucide-react";
import { toast } from "sonner";

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
import { useDashboardsStore } from "@/store/dashboardsStore";
import { useTenantId } from "@/lib/useTenantId";
import type { ButtonProps } from "@/components/ui/button";
import type { ChartSpec, QueryResponse } from "@/types/api";

interface AddToDashboardProps {
  spec: ChartSpec;
  title: string;
  /** Snapshot for specs that can't be re-run client-side (AI/NL charts). */
  data?: QueryResponse;
  variant?: ButtonProps["variant"];
  size?: ButtonProps["size"];
  className?: string;
}

const NEW = "__new__";

export function AddToDashboard({
  spec,
  title,
  data,
  variant = "outline",
  size = "sm",
  className,
}: AddToDashboardProps) {
  const tenantId = useTenantId();
  const navigate = useNavigate();
  const boards = useDashboardsStore((s) => (tenantId ? s.byTenant[tenantId] : undefined)) ?? [];
  const create = useDashboardsStore((s) => s.create);
  const addItem = useDashboardsStore((s) => s.addItem);

  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState<string>(NEW);
  const [newName, setNewName] = useState("");

  function handleSave() {
    if (!tenantId) return;
    let dashboardId = target;
    let dashboardName: string;
    if (target === NEW || boards.length === 0) {
      const board = create(tenantId, newName || "My dashboard");
      dashboardId = board.id;
      dashboardName = board.name;
    } else {
      dashboardName = boards.find((b) => b.id === dashboardId)?.name ?? "dashboard";
    }
    addItem(tenantId, dashboardId, { title, spec, data });
    setOpen(false);
    setNewName("");
    toast.success(`Added to “${dashboardName}”`, {
      action: {
        label: "Open",
        onClick: () => navigate(`/dashboards/${dashboardId}`),
      },
    });
  }

  const creating = target === NEW || boards.length === 0;

  return (
    <>
      <Button
        type="button"
        variant={variant}
        size={size}
        className={className}
        onClick={() => setOpen(true)}
        disabled={!tenantId}
      >
        <LayoutDashboard className="h-4 w-4" aria-hidden />
        Add to dashboard
      </Button>

      <Dialog open={open} onOpenChange={setOpen} title="Add to dashboard">
        <DialogHeader>
          <DialogTitle>Add to dashboard</DialogTitle>
          <DialogDescription>
            Pin “{title}” to a dashboard. Dashboards are saved in your browser.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {boards.length > 0 && (
            <div className="space-y-1.5">
              <Label htmlFor="dash-target">Dashboard</Label>
              <Select
                id="dash-target"
                value={target}
                onChange={(e) => setTarget(e.target.value)}
              >
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
          <Button onClick={handleSave}>
            <Plus className="h-4 w-4" aria-hidden />
            Save
          </Button>
        </DialogFooter>
      </Dialog>
    </>
  );
}
