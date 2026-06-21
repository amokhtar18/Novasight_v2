/**
 * DashboardDetail — view and edit a single dashboard. Toggle edit mode to
 * reorder tiles (dnd-kit), resize them, or remove them. Each tile re-runs its
 * saved chart's grounded query, so the dashboard always reflects current data.
 */

import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Check, LayoutDashboard, Pencil, Plus } from "lucide-react";

import { toast } from "sonner";

import { useAddDashboardTile, useDashboard, useUpdateDashboard } from "@/api/hooks";
import { useIdentity } from "@/lib/identity";
import { PageHeader } from "@/components/layout/PageHeader";
import { DashboardGrid } from "@/components/dashboard/DashboardGrid";
import { DashboardFilterBar } from "@/components/dashboard/DashboardFilterBar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
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
import type { DashboardTileCreate, SemanticFilter, TileKind } from "@/types/api";

export function DashboardDetail() {
  const { dashboardId = "" } = useParams();
  const { canEdit } = useIdentity();
  const { data: board, isLoading, isError } = useDashboard(dashboardId || null);
  const updateDashboard = useUpdateDashboard();

  const [editing, setEditing] = useState(false);
  const [nameDraft, setNameDraft] = useState("");
  const [addOpen, setAddOpen] = useState(false);
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

  // The cubes the dashboard's semantic tiles use — so the filter bar only offers
  // dimensions that can actually affect a tile.
  const tileCubes = useMemo(() => {
    const cubes = new Set<string>();
    for (const tile of board?.tiles ?? []) {
      const member = (tile.chart?.spec.query.metric_refs ?? [])[0];
      if (member && member.includes(".")) cubes.add(member.split(".")[0]);
    }
    return cubes;
  }, [board?.tiles]);

  /**
   * Apply a filter. An editor persists it on the dashboard (survives reload/sharing);
   * a read-only viewer filters locally only (the backend would reject the write).
   */
  function handleFilterChange(filter: SemanticFilter | null) {
    setActiveFilter(filter);
    if (board && canEdit) {
      updateDashboard.mutate({ id: board.id, patch: { filters: filter ? [filter] : [] } });
    }
  }

  /** Cross-filtering: a clicked chart point sets the dashboard filter to that value. */
  function handleCrossFilter(member: string, value: string) {
    handleFilterChange({ member, operator: "equals", values: [value] });
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
          canEdit ? (
            <>
              <Button asChild variant="outline" size="sm">
                <Link to="/build">
                  <Plus className="h-4 w-4" aria-hidden />
                  Add chart
                </Link>
              </Button>
              <Button variant="outline" size="sm" onClick={() => setAddOpen(true)}>
                <Plus className="h-4 w-4" aria-hidden />
                Add object
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
          ) : undefined
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
            <DashboardFilterBar
              value={activeFilter}
              onChange={handleFilterChange}
              cubes={tileCubes}
            />
          )}
          <DashboardGrid
            tiles={board.tiles}
            dashboardId={board.id}
            editing={editing}
            activeFilter={editing ? null : activeFilter}
            onCrossFilter={editing ? undefined : handleCrossFilter}
          />
        </>
      )}

      <AddObjectDialog open={addOpen} onOpenChange={setAddOpen} dashboardId={board.id} />
    </div>
  );
}

/**
 * AddObjectDialog — add a decoration tile (#10): text, markdown, image, divider, or a
 * filter slicer. Charts are added from the builder; this covers the rest.
 */
function AddObjectDialog({
  open,
  onOpenChange,
  dashboardId,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  dashboardId: string;
}) {
  const addTile = useAddDashboardTile();
  const [kind, setKind] = useState<Exclude<TileKind, "chart">>("text");
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [url, setUrl] = useState("");
  const [member, setMember] = useState("");
  const [label, setLabel] = useState("");

  function reset() {
    setKind("text");
    setTitle("");
    setText("");
    setUrl("");
    setMember("");
    setLabel("");
  }

  function buildContent(): Record<string, unknown> {
    if (kind === "text") return { text };
    if (kind === "markdown") return { markdown: text };
    if (kind === "image") return { url: url.trim() };
    if (kind === "divider") return label.trim() ? { label: label.trim() } : {};
    return { member: member.trim(), label: label.trim() || undefined }; // filter
  }

  function handleAdd() {
    if (kind === "image" && !url.trim()) {
      toast.error("An image URL is required");
      return;
    }
    if (kind === "filter" && !member.trim()) {
      toast.error("A filter member (e.g. sales.region) is required");
      return;
    }
    if ((kind === "text" || kind === "markdown") && !text.trim()) {
      toast.error("Add some text");
      return;
    }
    const tile: DashboardTileCreate = {
      kind,
      content: buildContent(),
      title: title.trim() || null,
    };
    addTile.mutate(
      { dashboardId, tile },
      {
        onSuccess: () => {
          onOpenChange(false);
          reset();
          toast.success("Object added");
        },
        onError: (err) =>
          toast.error(err instanceof Error ? err.message : "Could not add the object"),
      }
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Add object">
      <DialogHeader>
        <DialogTitle>Add object</DialogTitle>
        <DialogDescription>
          Add a text note, markdown, an image, a separator, or a filter slicer.
        </DialogDescription>
      </DialogHeader>

      <div className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="ao-kind">Kind</Label>
          <Select
            id="ao-kind"
            value={kind}
            onChange={(e) => setKind(e.target.value as Exclude<TileKind, "chart">)}
          >
            <option value="text">Text</option>
            <option value="markdown">Markdown</option>
            <option value="image">Image (URL)</option>
            <option value="divider">Divider</option>
            <option value="filter">Filter slicer</option>
          </Select>
        </div>

        {kind !== "divider" && (
          <div className="space-y-1.5">
            <Label htmlFor="ao-title">Title (optional)</Label>
            <Input id="ao-title" value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
        )}

        {(kind === "text" || kind === "markdown") && (
          <div className="space-y-1.5">
            <Label htmlFor="ao-text">{kind === "markdown" ? "Markdown" : "Text"}</Label>
            <textarea
              id="ao-text"
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={5}
              placeholder={kind === "markdown" ? "## Heading\n**bold** text" : "Your note…"}
              className="flex w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
          </div>
        )}

        {kind === "image" && (
          <div className="space-y-1.5">
            <Label htmlFor="ao-url">Image URL</Label>
            <Input
              id="ao-url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://…"
            />
          </div>
        )}

        {kind === "filter" && (
          <div className="space-y-1.5">
            <Label htmlFor="ao-member">Filter member</Label>
            <Input
              id="ao-member"
              value={member}
              onChange={(e) => setMember(e.target.value)}
              placeholder="e.g. sales.region"
            />
          </div>
        )}

        {(kind === "divider" || kind === "filter") && (
          <div className="space-y-1.5">
            <Label htmlFor="ao-label">Label (optional)</Label>
            <Input id="ao-label" value={label} onChange={(e) => setLabel(e.target.value)} />
          </div>
        )}
      </div>

      <DialogFooter>
        <Button variant="ghost" onClick={() => onOpenChange(false)}>
          Cancel
        </Button>
        <Button onClick={handleAdd} disabled={addTile.isPending}>
          {addTile.isPending ? "Adding…" : "Add object"}
        </Button>
      </DialogFooter>
    </Dialog>
  );
}
