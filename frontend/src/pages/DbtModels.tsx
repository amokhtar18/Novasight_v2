/**
 * DbtModels (Transforms) — the dbt model + test wizard (#5/#6).
 *
 * Lists the tenant's dbt model definitions and lets a superuser create one: a layer,
 * a materialization, the model SQL, and optional column data tests. Saving persists
 * the definition and regenerates the tenant's dbt project subtree; the dynamic dbt
 * run materializes it to ClickHouse.
 */

import { useState } from "react";
import { Boxes, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { useCreateDbtModel, useDbtModels, useDeleteDbtModel } from "@/api/hooks";
import { PageHeader } from "@/components/layout/PageHeader";
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
import type {
  DbtLayer,
  DbtMaterialization,
  DbtModelDefCreate,
  DbtTestDef,
  DbtTestType,
} from "@/types/api";

const LAYERS: DbtLayer[] = ["staging", "intermediate", "marts"];
const MATERIALIZATIONS: DbtMaterialization[] = ["view", "table", "incremental"];
const TEST_TYPES: DbtTestType[] = ["not_null", "unique", "accepted_values"];

interface TestRow {
  column: string;
  type: DbtTestType;
  values: string; // comma-separated, used for accepted_values
}

const emptyTest = (): TestRow => ({ column: "", type: "not_null", values: "" });

export function DbtModels() {
  const { data: models, isLoading } = useDbtModels();
  const createModel = useCreateDbtModel();
  const deleteModel = useDeleteDbtModel();

  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [layer, setLayer] = useState<DbtLayer>("marts");
  const [materialization, setMaterialization] = useState<DbtMaterialization>("table");
  const [sql, setSql] = useState("");
  const [tests, setTests] = useState<TestRow[]>([emptyTest()]);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);

  function reset() {
    setName("");
    setLayer("marts");
    setMaterialization("table");
    setSql("");
    setTests([emptyTest()]);
  }

  async function handleCreate() {
    if (!name.trim() || !sql.trim()) {
      toast.error("Name and SQL are required");
      return;
    }
    const cleanTests: DbtTestDef[] = tests
      .filter((t) => t.column.trim())
      .map((t) => ({
        column_name: t.column.trim(),
        test_type: t.type,
        config:
          t.type === "accepted_values"
            ? { values: t.values.split(",").map((v) => v.trim()).filter(Boolean) }
            : {},
      }));

    const payload: DbtModelDefCreate = {
      name: name.trim(),
      layer,
      materialization,
      sql: sql.trim(),
      tests: cleanTests,
    };
    try {
      const created = await createModel.mutateAsync(payload);
      setOpen(false);
      reset();
      toast.success(`Created model “${created.name}”`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not create the model");
    }
  }

  function handleDelete(id: string) {
    deleteModel.mutate(id, {
      onError: (err) =>
        toast.error(err instanceof Error ? err.message : "Could not delete the model"),
    });
    setPendingDelete(null);
  }

  return (
    <div className="animate-in-up">
      <PageHeader
        title="Transforms"
        description="dbt models that shape raw data into marts. Define one here; tests become quality gates and it materializes to ClickHouse."
        actions={
          <Button onClick={() => setOpen(true)}>
            <Plus className="h-4 w-4" aria-hidden />
            New model
          </Button>
        }
      />

      {isLoading ? (
        <div className="flex h-48 items-center justify-center">
          <Spinner label="Loading models" />
        </div>
      ) : !models || models.length === 0 ? (
        <EmptyState
          icon={<Boxes className="h-6 w-6" />}
          title="No dbt models yet"
          description="Define a transformation (SQL + tests) to build a mart from your raw data."
          action={
            <Button onClick={() => setOpen(true)}>
              <Plus className="h-4 w-4" aria-hidden />
              New model
            </Button>
          }
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {models.map((m) => (
            <div
              key={m.id}
              className="group relative rounded-xl border bg-card/70 p-5 transition-colors hover:border-primary/50"
            >
              <span className="mb-3 flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <Boxes className="h-5 w-5" aria-hidden />
              </span>
              <p className="truncate font-medium">{m.name}</p>
              <p className="mt-1 truncate text-xs text-muted-foreground">
                {m.layer} · {m.materialization}
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Badge variant="secondary">
                  {m.tests.length} test{m.tests.length === 1 ? "" : "s"}
                </Badge>
                {!m.enabled && <Badge variant="info">disabled</Badge>}
              </div>
              <button
                type="button"
                onClick={() => setPendingDelete(m.id)}
                aria-label={`Delete ${m.name}`}
                className="absolute right-3 top-3 rounded-md p-1.5 text-muted-foreground opacity-0 transition-opacity hover:bg-destructive/10 hover:text-destructive focus-visible:opacity-100 group-hover:opacity-100"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Create wizard */}
      <Dialog open={open} onOpenChange={setOpen} title="New dbt model">
        <DialogHeader>
          <DialogTitle>New dbt model</DialogTitle>
          <DialogDescription>
            Write the transformation SQL and optional column tests.
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-[60vh] space-y-4 overflow-y-auto pr-1">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="space-y-1.5">
              <Label htmlFor="dm-name">Name</Label>
              <Input id="dm-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="mart_orders" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="dm-layer">Layer</Label>
              <Select id="dm-layer" value={layer} onChange={(e) => setLayer(e.target.value as DbtLayer)}>
                {LAYERS.map((l) => (
                  <option key={l} value={l}>
                    {l}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="dm-mat">Materialization</Label>
              <Select
                id="dm-mat"
                value={materialization}
                onChange={(e) => setMaterialization(e.target.value as DbtMaterialization)}
              >
                {MATERIALIZATIONS.map((mt) => (
                  <option key={mt} value={mt}>
                    {mt}
                  </option>
                ))}
              </Select>
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="dm-sql">SQL</Label>
            <textarea
              id="dm-sql"
              value={sql}
              onChange={(e) => setSql(e.target.value)}
              rows={6}
              placeholder="select region, sum(amount) as total from {{ ref('stg_orders') }} group by 1"
              className="flex w-full rounded-md border border-input bg-transparent px-3 py-2 font-mono text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
          </div>

          <div className="space-y-2 rounded-lg border bg-background/40 p-3">
            <div className="flex items-center justify-between">
              <h4 className="text-sm font-medium">Column tests</h4>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setTests((rows) => [...rows, emptyTest()])}
              >
                <Plus className="h-3.5 w-3.5" aria-hidden />
                Add
              </Button>
            </div>
            {tests.map((row, i) => (
              <div key={i} className="grid grid-cols-[1fr_8rem_1fr_auto] items-end gap-2">
                <div className="space-y-1">
                  <Label htmlFor={`t-col-${i}`} className="text-xs text-muted-foreground">
                    Column
                  </Label>
                  <Input
                    id={`t-col-${i}`}
                    value={row.column}
                    onChange={(e) =>
                      setTests((rows) => rows.map((r, j) => (j === i ? { ...r, column: e.target.value } : r)))
                    }
                    placeholder="region"
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor={`t-type-${i}`} className="text-xs text-muted-foreground">
                    Test
                  </Label>
                  <Select
                    id={`t-type-${i}`}
                    value={row.type}
                    onChange={(e) =>
                      setTests((rows) =>
                        rows.map((r, j) => (j === i ? { ...r, type: e.target.value as DbtTestType } : r))
                      )
                    }
                  >
                    {TEST_TYPES.map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label htmlFor={`t-vals-${i}`} className="text-xs text-muted-foreground">
                    Values
                  </Label>
                  <Input
                    id={`t-vals-${i}`}
                    value={row.values}
                    onChange={(e) =>
                      setTests((rows) => rows.map((r, j) => (j === i ? { ...r, values: e.target.value } : r)))
                    }
                    placeholder={row.type === "accepted_values" ? "west, east" : "(n/a)"}
                    disabled={row.type !== "accepted_values"}
                  />
                </div>
                <button
                  type="button"
                  onClick={() => setTests((rows) => (rows.length > 1 ? rows.filter((_, j) => j !== i) : rows))}
                  aria-label={`Remove test ${i + 1}`}
                  className="mb-1 rounded p-2 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            ))}
          </div>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button onClick={handleCreate} disabled={createModel.isPending}>
            {createModel.isPending ? "Creating…" : "Create model"}
          </Button>
        </DialogFooter>
      </Dialog>

      {/* Delete confirm */}
      <Dialog
        open={pendingDelete !== null}
        onOpenChange={(o) => !o && setPendingDelete(null)}
        title="Delete model"
      >
        <DialogHeader>
          <DialogTitle>Delete dbt model?</DialogTitle>
          <DialogDescription>
            This removes the model from the tenant's dbt project on the next regeneration.
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
