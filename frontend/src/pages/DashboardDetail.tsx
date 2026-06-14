/**
 * DashboardDetail — view and edit a single dashboard. Toggle edit mode to
 * reorder tiles (dnd-kit), resize them, or remove them. Each tile re-runs its
 * saved chart's grounded query, so the dashboard always reflects current data.
 */

import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Check, LayoutDashboard, Pencil, Plus } from "lucide-react";

import { useDashboard, useUpdateDashboard } from "@/api/hooks";
import { PageHeader } from "@/components/layout/PageHeader";
import { DashboardGrid } from "@/components/dashboard/DashboardGrid";
import { DashboardFilterBar } from "@/components/dashboard/DashboardFilterBar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Spinner } from "@/components/ui/spinner";
import { EmptyState } from "@/components/ui/empty-state";
import type { SemanticFilter } from "@/types/api";

export function DashboardDetail() {
  const { dashboardId = "" } = useParams();
  const { data: board, isLoading, isError } = useDashboard(dashboardId || null);
  const updateDashboard = useUpdateDashboard();

  const [editing, setEditing] = useState(false);
  const [nameDraft, setNameDraft] = useState("");
  const [activeFilter, setActiveFilter] = useState<SemanticFilter | null>(null);
  // Track which dashboard the active filter was initialised from, so we seed it from
  // the persisted filters once per dashboard without an effect (and without clobbering
  // an in-session edit on a background refetch). This is React's "adjust state during
  // render" pattern.
  const [filterInitFor, setFilterInitFor] = useState<string | null>(null);
  if (board && filterInitFor !== board.id) {
    setFilterInitFor(board.id);
    setActiveFilter(board.filters?.[0] ?? null);
  }

  function commitRename() {
    if (board && nameDraft.trim() && nameDraft !== board.name) {
      updateDashboard.mutate({ id: board.id, patch: { name: nameDraft.trim() } });
    }
  }

  /** Apply a filter and persist it on the dashboard so it survives reload/sharing. */
  function handleFilterChange(filter: SemanticFilter | null) {
    setActiveFilter(filter);
    if (board) {
      updateDashboard.mutate({ id: board.id, patch: { filters: filter ? [filter] : [] } });
    }
  }

  const backLink = (
    <Link
      to="/dashboards"
      className="mb-4 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
    >
      <ArrowLeft className="h-4 w-4" aria-hidden />
      All dashboards
    </Link>
  );

  if (isLoading) {
    return (
      <div className="animate-in-up">
        {backLink}
        <div className="flex h-48 items-center justify-center">
          <Spinner label="Loading dashboard" />
        </div>
      </div>
    );
  }

  if (isError || !board) {
    return (
      <div className="animate-in-up">
        {backLink}
        <EmptyState
          icon={<LayoutDashboard className="h-6 w-6" />}
          title="Dashboard not found"
          description="It may have been deleted, or belongs to a different tenant."
        />
      </div>
    );
  }

  return (
    <div className="animate-in-up">
      {backLink}

      <PageHeader
        title={
          editing ? (
            <Input
              value={nameDraft}
              onChange={(e) => setNameDraft(e.target.value)}
              onBlur={commitRename}
              aria-label="Dashboard name"
              className="h-9 w-72 text-lg"
            />
          ) : (
            board.name
          )
        }
        description={`${board.tiles.length} chart${board.tiles.length === 1 ? "" : "s"}`}
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
                else commitRename();
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

      {board.tiles.length === 0 ? (
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
        <>
          {!editing && (
            <DashboardFilterBar value={activeFilter} onChange={handleFilterChange} />
          )}
          <DashboardGrid
            tiles={board.tiles}
            dashboardId={board.id}
            editing={editing}
            activeFilter={editing ? null : activeFilter}
          />
        </>
      )}
    </div>
  );
}
