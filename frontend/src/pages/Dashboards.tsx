/**
 * Dashboards — list of the tenant's saved dashboards (client-side persisted).
 * Create new boards and open or delete existing ones.
 */

import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { LayoutDashboard, Plus, Trash2 } from "lucide-react";

import { useDashboardsStore } from "@/store/dashboardsStore";
import { useTenantId } from "@/lib/useTenantId";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import {
  Dialog,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { formatRelativeTime } from "@/lib/format";

export function Dashboards() {
  const tenantId = useTenantId();
  const navigate = useNavigate();
  const boards =
    useDashboardsStore((s) => (tenantId ? s.byTenant[tenantId] : undefined)) ?? [];
  const create = useDashboardsStore((s) => s.create);
  const remove = useDashboardsStore((s) => s.remove);

  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);

  function handleCreate() {
    if (!tenantId) return;
    const board = create(tenantId, name || "My dashboard");
    setOpen(false);
    setName("");
    navigate(`/dashboards/${board.id}`);
  }

  return (
    <div className="animate-in-up">
      <PageHeader
        title="Dashboards"
        description="Collections of charts you've pinned. Saved in your browser, scoped to this tenant."
        actions={
          <Button onClick={() => setOpen(true)} disabled={!tenantId}>
            <Plus className="h-4 w-4" aria-hidden />
            New dashboard
          </Button>
        }
      />

      {boards.length === 0 ? (
        <EmptyState
          icon={<LayoutDashboard className="h-6 w-6" />}
          title="No dashboards yet"
          description="Build a chart and pin it, or create an empty dashboard to start."
          action={
            <Button onClick={() => setOpen(true)} disabled={!tenantId}>
              <Plus className="h-4 w-4" aria-hidden />
              New dashboard
            </Button>
          }
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {boards.map((b) => (
            <div
              key={b.id}
              className="group relative rounded-xl border bg-card/70 p-5 transition-colors hover:border-primary/50"
            >
              <Link to={`/dashboards/${b.id}`} className="block focus-visible:outline-none">
                <span className="mb-3 flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <LayoutDashboard className="h-5 w-5" aria-hidden />
                </span>
                <p className="truncate font-medium">{b.name}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Updated {formatRelativeTime(b.updatedAt)}
                </p>
                <Badge variant="secondary" className="mt-3">
                  {b.items.length} chart{b.items.length === 1 ? "" : "s"}
                </Badge>
              </Link>
              <button
                type="button"
                onClick={() => setPendingDelete(b.id)}
                aria-label={`Delete ${b.name}`}
                className="absolute right-3 top-3 rounded-md p-1.5 text-muted-foreground opacity-0 transition-opacity hover:bg-destructive/10 hover:text-destructive focus-visible:opacity-100 group-hover:opacity-100"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Create dialog */}
      <Dialog open={open} onOpenChange={setOpen} title="New dashboard">
        <DialogHeader>
          <DialogTitle>New dashboard</DialogTitle>
          <DialogDescription>Give your dashboard a name.</DialogDescription>
        </DialogHeader>
        <div className="space-y-1.5">
          <Label htmlFor="new-dash">Name</Label>
          <Input
            id="new-dash"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Sales overview"
            autoFocus
            onKeyDown={(e) => e.key === "Enter" && handleCreate()}
          />
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button onClick={handleCreate}>Create</Button>
        </DialogFooter>
      </Dialog>

      {/* Delete confirm */}
      <Dialog
        open={pendingDelete !== null}
        onOpenChange={(o) => !o && setPendingDelete(null)}
        title="Delete dashboard"
      >
        <DialogHeader>
          <DialogTitle>Delete dashboard?</DialogTitle>
          <DialogDescription>
            This removes the dashboard and its tiles from this browser. This can't be undone.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setPendingDelete(null)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={() => {
              if (tenantId && pendingDelete) remove(tenantId, pendingDelete);
              setPendingDelete(null);
            }}
          >
            Delete
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}
