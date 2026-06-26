/**
 * NativeFilterEditor — add/edit a native filter (Slice C). Picks kind + governed
 * member, label, scope (auto / specific tiles), an optional cascading parent (value
 * filters only — the picker offers only value parents and excludes self), and required.
 */
import { useMemo, useState } from "react";

import { useSemanticModels } from "@/api/hooks";
import {
  Dialog, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import type { DashboardTileRead, NativeFilter, NativeFilterKind } from "@/types/api";

interface Props {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  initial: NativeFilter | null;
  existing: NativeFilter[];
  tiles: DashboardTileRead[];
  onSave: (f: NativeFilter) => void;
  onRemove?: (id: string) => void;
}

let _seq = 0;
const newId = () => `nf_${Date.now()}_${_seq++}`;

export function NativeFilterEditor({ open, onOpenChange, initial, existing, tiles, onSave, onRemove }: Props) {
  const { data: models } = useSemanticModels();
  const [kind, setKind] = useState<NativeFilterKind>(initial?.kind ?? "value");
  const [member, setMember] = useState(initial?.member ?? "");
  const [label, setLabel] = useState(initial?.label ?? "");
  const [parentId, setParentId] = useState(initial?.parent_id ?? "");
  const [scopeMode, setScopeMode] = useState<"auto" | "tiles">(initial?.scope?.mode ?? "auto");
  const [tileIds, setTileIds] = useState<string[]>(initial?.scope?.tile_ids ?? []);
  const [required, setRequired] = useState(initial?.required ?? false);

  // Dimensions for value/time filters; measures + number dimensions for numeric.
  const memberOptions = useMemo(() => {
    const out: { value: string; label: string }[] = [];
    for (const m of models ?? []) {
      if (kind === "numeric") {
        for (const f of m.measures) out.push({ value: f.name, label: `${m.title} · ${f.title}` });
        for (const d of m.dimensions) if (d.type === "number") out.push({ value: d.name, label: `${m.title} · ${d.title}` });
      } else if (kind === "time") {
        for (const d of m.dimensions) if (d.type === "time") out.push({ value: d.name, label: `${m.title} · ${d.title}` });
      } else {
        for (const d of m.dimensions) out.push({ value: d.name, label: `${m.title} · ${d.title}` });
      }
    }
    return out;
  }, [models, kind]);

  const parentOptions = existing.filter((f) => f.kind === "value" && f.id !== initial?.id);

  function handleSave() {
    if (!member) return;
    const f: NativeFilter = {
      id: initial?.id ?? newId(),
      kind,
      member,
      label: label.trim() || null,
      operator: kind === "value" ? (initial?.operator ?? "equals") : undefined,
      default_values: initial?.default_values ?? [],
      date_range: initial?.date_range ?? null,
      numeric_range: initial?.numeric_range ?? null,
      scope: { mode: scopeMode, tile_ids: scopeMode === "tiles" ? tileIds : [] },
      parent_id: kind === "value" && parentId ? parentId : null,
      required,
    };
    onSave(f);
    onOpenChange(false);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={initial ? "Edit filter" : "Add filter"}>
      <DialogHeader>
        <DialogTitle>{initial ? "Edit filter" : "Add filter"}</DialogTitle>
      </DialogHeader>

      <div className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="nf-kind">Kind</Label>
          <Select id="nf-kind" value={kind} onChange={(e) => { setKind(e.target.value as NativeFilterKind); setMember(""); }}>
            <option value="value">Value</option>
            <option value="time">Time range</option>
            <option value="numeric">Numeric range</option>
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="nf-member">Dimension</Label>
          <Select id="nf-member" value={member} onChange={(e) => setMember(e.target.value)}>
            <option value="">Choose…</option>
            {memberOptions.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="nf-label">Label (optional)</Label>
          <Input id="nf-label" value={label ?? ""} onChange={(e) => setLabel(e.target.value)} />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="nf-scope">Applies to</Label>
          <Select id="nf-scope" value={scopeMode} onChange={(e) => setScopeMode(e.target.value as "auto" | "tiles")}>
            <option value="auto">All compatible tiles</option>
            <option value="tiles">Specific tiles…</option>
          </Select>
          {scopeMode === "tiles" && (
            <div className="flex max-h-32 flex-col gap-1 overflow-auto rounded border p-2">
              {tiles.filter((t) => t.kind === "chart").map((t) => (
                <label key={t.id} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={tileIds.includes(t.id)}
                    onChange={(e) =>
                      setTileIds(e.target.checked ? [...tileIds, t.id] : tileIds.filter((x) => x !== t.id))
                    }
                  />
                  {t.title ?? t.chart?.name ?? "Chart"}
                </label>
              ))}
            </div>
          )}
        </div>

        {kind === "value" && (
          <div className="space-y-1.5">
            <Label htmlFor="nf-parent">Parent filter (cascading, optional)</Label>
            <Select id="nf-parent" value={parentId ?? ""} onChange={(e) => setParentId(e.target.value)}>
              <option value="">None</option>
              {parentOptions.map((p) => (
                <option key={p.id} value={p.id}>{p.label ?? p.member}</option>
              ))}
            </Select>
          </div>
        )}

        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={required} onChange={(e) => setRequired(e.target.checked)} />
          Required
        </label>
      </div>

      <DialogFooter>
        {initial && onRemove && (
          <Button variant="ghost" className="text-destructive" onClick={() => { onRemove(initial.id); onOpenChange(false); }}>
            Remove
          </Button>
        )}
        <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
        <Button onClick={handleSave} disabled={!member}>Save</Button>
      </DialogFooter>
    </Dialog>
  );
}
