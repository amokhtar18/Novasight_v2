/**
 * DashboardDetail — view and edit a single dashboard. Toggle edit mode to
 * reorder tiles (dnd-kit), resize them, or remove them. Each tile re-runs its
 * saved chart's grounded query, so the dashboard always reflects current data.
 *
 * Native filters (Slice C): the dashboard persists a `native_filters` config;
 * at view time each filter's live selection is held in session state and
 * resolved per-tile. A transient cross-filter overlay is also session-only.
 */

import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Check, LayoutDashboard, Pencil, Plus } from "lucide-react";

import { toast } from "sonner";

import { useAddDashboardTile, useDashboard, useUpdateDashboard } from "@/api/hooks";
import { useIdentity } from "@/lib/identity";
import { defaultSelection } from "@/lib/dashboardFilters";
import type { FilterSelection, FilterSelections } from "@/lib/dashboardFilters";
import { PageHeader } from "@/components/layout/PageHeader";
import { DashboardGrid } from "@/components/dashboard/DashboardGrid";
import { DashboardFilterBar } from "@/components/dashboard/DashboardFilterBar";
import { NativeFilterEditor } from "@/components/dashboard/NativeFilterEditor";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
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
import type { DashboardTileCreate, NativeFilter, SemanticFilter, SelectionPair, TileKind } from "@/types/api";

export function DashboardDetail() {
  const { dashboardId = "" } = useParams();
  const { canEdit } = useIdentity();
  const { data: board, isLoading, isError } = useDashboard(dashboardId || null);
  const updateDashboard = useUpdateDashboard();

  const [editing, setEditing] = useState(false);
  const [nameDraft, setNameDraft] = useState("");
  const [addOpen, setAddOpen] = useState(false);

  // --- Native filter state ---
  const filters: NativeFilter[] = board?.native_filters ?? [];
  const [selections, setSelections] = useState<FilterSelections>({});
  const [crossFilter, setCrossFilter] = useState<SemanticFilter[]>([]);
  const [editorFor, setEditorFor] = useState<{ open: boolean; id: string | null }>({ open: false, id: null });

  // Seed live selections from the persisted defaults once per dashboard (adjust-during-render).
  const [seedFor, setSeedFor] = useState<string | null>(null);
  if (board && seedFor !== board.id) {
    setSeedFor(board.id);
    const seeded: FilterSelections = {};
    for (const f of board.native_filters ?? []) seeded[f.id] = defaultSelection(f);
    setSelections(seeded);
    setCrossFilter([]);
  }

  function onSelectionChange(id: string, sel: FilterSelection) {
    setSelections((prev) => ({ ...prev, [id]: sel }));
  }
  function onClearAll() {
    const reset: FilterSelections = {};
    for (const f of filters) reset[f.id] = defaultSelection(f);
    setSelections(reset);
    setCrossFilter([]);
  }
  function persistFilters(next: NativeFilter[]) {
    if (board && canEdit) updateDashboard.mutate({ id: board.id, patch: { native_filters: next } });
  }
  function saveFilter(f: NativeFilter) {
    const next = filters.some((x) => x.id === f.id)
      ? filters.map((x) => (x.id === f.id ? f : x))
      : [...filters, f];
    persistFilters(next);
    setSelections((prev) => ({ ...prev, [f.id]: defaultSelection(f) }));
  }
  function removeFilter(id: string) {
    persistFilters(filters.filter((x) => x.id !== id));
    // Drop the orphaned live selection so it can't linger in session state.
    setSelections((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
  }
  /** Cross-filter: clicked points become a transient session value overlay list. */
  function handleCrossFilter(pairs: SelectionPair[]) {
    setCrossFilter(pairs.map((p) => ({ member: p.member, operator: "equals", values: [p.value] })));
  }

  function commitRename() {
    if (board && nameDraft.trim() && nameDraft !== board.name) {
      updateDashboard.mutate({ id: board.id, patch: { name: nameDraft.trim() } });
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
          Drag tiles to move · drag a tile's edge to resize · use the size control or remove
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
        <div className="min-w-0">
          <DashboardFilterBar
              filters={filters}
              selections={selections}
              onSelectionChange={onSelectionChange}
              onClearAll={onClearAll}
              editing={editing}
              onAddFilter={() => setEditorFor({ open: true, id: null })}
              onEditFilter={(id) => setEditorFor({ open: true, id })}
            />
          <DashboardGrid
            tiles={board.tiles}
            dashboardId={board.id}
            editing={editing}
            filters={filters}
            selections={selections}
            crossFilter={editing ? [] : crossFilter}
            onCrossFilter={editing ? undefined : handleCrossFilter}
          />
        </div>
      )}

      <AddObjectDialog open={addOpen} onOpenChange={setAddOpen} dashboardId={board.id} />

      {editorFor.open && (
        <NativeFilterEditor
          open={editorFor.open}
          onOpenChange={(o) => setEditorFor((s) => ({ ...s, open: o }))}
          initial={editorFor.id ? filters.find((f) => f.id === editorFor.id) ?? null : null}
          existing={filters}
          tiles={board.tiles}
          onSave={saveFilter}
          onRemove={removeFilter}
        />
      )}
    </div>
  );
}

/**
 * AddObjectDialog — add a decoration tile (#10): text, markdown, image, or divider.
 * Charts are added from the builder; this covers the rest.
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
  const [label, setLabel] = useState("");

  function reset() {
    setKind("text");
    setTitle("");
    setText("");
    setUrl("");
    setLabel("");
  }

  function buildContent(): Record<string, unknown> {
    if (kind === "text") return { text };
    if (kind === "markdown") return { markdown: text };
    if (kind === "image") return { url: url.trim() };
    return label.trim() ? { label: label.trim() } : {}; // divider
  }

  function handleAdd() {
    if (kind === "image" && !url.trim()) {
      toast.error("An image URL is required");
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
          Add a text note, markdown, an image, or a separator.
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
            <Textarea
              id="ao-text"
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={5}
              placeholder={kind === "markdown" ? "## Heading\n**bold** text" : "Your note…"}
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

        {kind === "divider" && (
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
