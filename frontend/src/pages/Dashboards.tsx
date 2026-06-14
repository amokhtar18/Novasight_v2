/**
 * Dashboards — list of the tenant's saved dashboards (server-persisted).
 * Create new boards and open or delete existing ones.
 */

import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { LayoutDashboard, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { useCreateDashboard, useDashboards, useDeleteDashboard } from "@/api/hooks";
import { useIdentity } from "@/lib/identity";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
import { formatRelativeTime } from "@/lib/format";

export function Dashboards() {
  const navigate = useNavigate();
  const { canEdit } = useIdentity();
  const { data: boards, isLoading } = useDashboards();
  const createDashboard = useCreateDashboard();
  const deleteDashboard = useDeleteDashboard();

  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);

  async function handleCreate() {
    try {
      const board = await createDashboard.mutateAsync({ name: name || "My dashboard" });
      setOpen(false);
      setName("");
      navigate(`/dashboards/${board.id}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not create the dashboard");
    }
  }

  function handleDelete(id: string) {
    deleteDashboard.mutate(id, {
      onError: (err) =>
        toast.error(err instanceof Error ? err.message : "Could not delete the dashboard"),
    });
    setPendingDelete(null);
  }

  return (
    <div className="animate-in-up">
      <PageHeader
        title="Dashboards"
        description="Collections of charts you've pinned. Saved to your account and shared across this tenant."
        actions={
          canEdit ? (
            <Button onClick={() => setOpen(true)}>
              <Plus className="h-4 w-4" aria-hidden />
              New dashboard
            </Button>
          ) : undefined
        }
      />

      {isLoading ? (
        <div className="flex h-48 items-center justify-center">
          <Spinner label="Loading dashboards" />
        </div>
      ) : !boards || boards.length === 0 ? (
        <EmptyState
          icon={<LayoutDashboard className="h-6 w-6" />}
          title="No dashboards yet"
          description="Build a chart and pin it, or create an empty dashboard to start."
          action={
            canEdit ? (
              <Button onClick={() => setOpen(true)}>
                <Plus className="h-4 w-4" aria-hidden />
                New dashboard
              </Button>
            ) : undefined
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
                  Updated {formatRelativeTime(b.updated_at)}
                </p>
                <Badge variant="secondary" className="mt-3">
                  {b.tile_count} chart{b.tile_count === 1 ? "" : "s"}
                </Badge>
              </Link>
              {canEdit && (
                <button
                  type="button"
                  onClick={() => setPendingDelete(b.id)}
                  aria-label={`Delete ${b.name}`}
                  className="absolute right-3 top-3 rounded-md p-1.5 text-muted-foreground opacity-0 transition-opacity hover:bg-destructive/10 hover:text-destructive focus-visible:opacity-100 group-hover:opacity-100"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              )}
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
          <Button onClick={handleCreate} disabled={createDashboard.isPending}>
            Create
          </Button>
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
            This permanently removes the dashboard and its tiles. This can't be undone.
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
