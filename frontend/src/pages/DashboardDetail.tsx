/**
 * DashboardDetail — view and edit a single dashboard. Toggle edit mode to
 * reorder tiles (dnd-kit), resize them, or remove them. Tiles re-run their
 * query live where possible, otherwise render their saved snapshot.
 */

import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Check, LayoutDashboard, Pencil, Plus } from "lucide-react";

import { useDashboardsStore } from "@/store/dashboardsStore";
import { useTenantId } from "@/lib/useTenantId";
import { PageHeader } from "@/components/layout/PageHeader";
import { DashboardGrid } from "@/components/dashboard/DashboardGrid";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";

export function DashboardDetail() {
  const { dashboardId = "" } = useParams();
  const tenantId = useTenantId();
  const board = useDashboardsStore((s) =>
    tenantId ? s.byTenant[tenantId]?.find((b) => b.id === dashboardId) : undefined
  );
  const rename = useDashboardsStore((s) => s.rename);

  const [editing, setEditing] = useState(false);
  const [nameDraft, setNameDraft] = useState("");

  if (!tenantId || !board) {
    return (
      <div className="animate-in-up">
        <Link
          to="/dashboards"
          className="mb-4 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden />
          All dashboards
        </Link>
        <EmptyState
          icon={<LayoutDashboard className="h-6 w-6" />}
          title="Dashboard not found"
          description="It may have been deleted, or belongs to a different tenant/browser."
        />
      </div>
    );
  }

  return (
    <div className="animate-in-up">
      <Link
        to="/dashboards"
        className="mb-4 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden />
        All dashboards
      </Link>

      <PageHeader
        title={
          editing ? (
            <Input
              value={nameDraft}
              onChange={(e) => setNameDraft(e.target.value)}
              onBlur={() => rename(tenantId, board.id, nameDraft)}
              aria-label="Dashboard name"
              className="h-9 w-72 text-lg"
            />
          ) : (
            board.name
          )
        }
        description={`${board.items.length} chart${board.items.length === 1 ? "" : "s"}`}
        actions={
          <>
            <Button asChild variant="outline" size="sm">
              <Link to="/build">
                <Plus className="h-4 w-4" aria-hidden />
                Add chart
              </Link>
            </Button>
            <Button
              size="sm"
              variant={editing ? "default" : "outline"}
              onClick={() => {
                if (!editing) setNameDraft(board.name);
                else rename(tenantId, board.id, nameDraft);
                setEditing((v) => !v);
              }}
            >
              {editing ? (
                <>
                  <Check className="h-4 w-4" aria-hidden />
                  Done
                </>
              ) : (
                <>
                  <Pencil className="h-4 w-4" aria-hidden />
                  Edit
                </>
              )}
            </Button>
          </>
        }
      />

      {editing && (
        <Badge variant="info" className="mb-4">
          Drag tiles to reorder · resize or remove with the tile controls
        </Badge>
      )}

      {board.items.length === 0 ? (
        <EmptyState
          icon={<LayoutDashboard className="h-6 w-6" />}
          title="This dashboard is empty"
          description="Build a chart and pin it here, or open the builder to get started."
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
        <DashboardGrid
          items={board.items}
          tenantId={tenantId}
          dashboardId={board.id}
          editing={editing}
        />
      )}
    </div>
  );
}
