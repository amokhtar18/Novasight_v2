/**
 * SemanticModels — define governed semantic models (the #8 wizard).
 *
 * Lists the tenant's semantic-model definitions and lets a superuser create one:
 * pick a base serving table (a dbt mart), then declare measures and dimensions.
 * Saving persists the definition and regenerates the tenant's Cube model file, so
 * the model becomes queryable in the chart builder (semantic path) and to AI.
 */

import { useState } from "react";
import { Layers, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import {
  useCreateSemanticModelDef,
  useDeleteSemanticModelDef,
  useSemanticModelDefs,
} from "@/api/hooks";
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
  DimensionType,
  MeasureType,
  SemanticJoinRelationship,
  SemanticModelDefCreate,
} from "@/types/api";

const MEASURE_TYPES: MeasureType[] = ["count", "sum", "avg", "min", "max", "count_distinct"];
const DIMENSION_TYPES: DimensionType[] = ["string", "number", "time", "boolean"];
const JOIN_RELATIONSHIPS: SemanticJoinRelationship[] = [
  "many_to_one",
  "one_to_many",
  "one_to_one",
];

interface MeasureRow {
  name: string;
  type: MeasureType;
  sql: string;
}
interface DimensionRow {
  name: string;
  type: DimensionType;
  sql: string;
}
interface JoinRow {
  name: string;
  relationship: SemanticJoinRelationship;
  localKey: string;
  foreignKey: string;
}

const emptyMeasure = (): MeasureRow => ({ name: "", type: "sum", sql: "" });
const emptyDimension = (): DimensionRow => ({ name: "", type: "string", sql: "" });
const emptyJoin = (): JoinRow => ({
  name: "",
  relationship: "many_to_one",
  localKey: "",
  foreignKey: "",
});

export function SemanticModels() {
  const { data: models, isLoading } = useSemanticModelDefs();
  const createModel = useCreateSemanticModelDef();
  const deleteModel = useDeleteSemanticModelDef();

  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [baseTable, setBaseTable] = useState("");
  const [measures, setMeasures] = useState<MeasureRow[]>([emptyMeasure()]);
  const [dimensions, setDimensions] = useState<DimensionRow[]>([emptyDimension()]);
  const [joins, setJoins] = useState<JoinRow[]>([]);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);

  function reset() {
    setName("");
    setBaseTable("");
    setMeasures([emptyMeasure()]);
    setDimensions([emptyDimension()]);
    setJoins([]);
  }

  async function handleCreate() {
    const cleanMeasures = measures
      .filter((m) => m.name.trim())
      .map((m) => ({
        name: m.name.trim(),
        type: m.type,
        sql: m.sql.trim() || (m.type === "count" ? null : ""),
      }));
    const cleanDimensions = dimensions
      .filter((d) => d.name.trim())
      .map((d) => ({ name: d.name.trim(), type: d.type, sql: d.sql.trim() }));
    const cleanJoins = joins
      .filter((j) => j.name.trim() && j.localKey.trim() && j.foreignKey.trim())
      .map((j) => ({
        name: j.name.trim(),
        relationship: j.relationship,
        local_key: j.localKey.trim(),
        foreign_key: j.foreignKey.trim(),
      }));

    if (!name.trim() || !baseTable.trim()) {
      toast.error("Name and base table are required");
      return;
    }
    if (cleanMeasures.length === 0 && cleanDimensions.length === 0) {
      toast.error("Add at least one measure or dimension");
      return;
    }

    const payload: SemanticModelDefCreate = {
      name: name.trim(),
      base_table: baseTable.trim(),
      config: {
        measures: cleanMeasures,
        dimensions: cleanDimensions,
        ...(cleanJoins.length > 0 ? { joins: cleanJoins } : {}),
      },
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
        title="Semantic models"
        description="Governed metrics and dimensions over your data marts. Build a model here, then chart it or ask AI about it."
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
          icon={<Layers className="h-6 w-6" />}
          title="No semantic models yet"
          description="Define one over a data mart to expose governed measures and dimensions."
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
                <Layers className="h-5 w-5" aria-hidden />
              </span>
              <p className="truncate font-medium">{m.name}</p>
              <p className="mt-1 truncate text-xs text-muted-foreground">over {m.base_table}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Badge variant="secondary">
                  {m.config.measures.length} measure{m.config.measures.length === 1 ? "" : "s"}
                </Badge>
                <Badge variant="secondary">
                  {m.config.dimensions.length} dimension
                  {m.config.dimensions.length === 1 ? "" : "s"}
                </Badge>
                {m.config.joins && m.config.joins.length > 0 && (
                  <Badge variant="secondary">
                    {m.config.joins.length} join{m.config.joins.length === 1 ? "" : "s"}
                  </Badge>
                )}
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
      <Dialog open={open} onOpenChange={setOpen} title="New semantic model">
        <DialogHeader>
          <DialogTitle>New semantic model</DialogTitle>
          <DialogDescription>
            Define governed measures and dimensions over a serving table (a dbt mart).
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-[60vh] space-y-4 overflow-y-auto pr-1">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="sm-name">Model name</Label>
              <Input
                id="sm-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. sales"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="sm-table">Base table</Label>
              <Input
                id="sm-table"
                value={baseTable}
                onChange={(e) => setBaseTable(e.target.value)}
                placeholder="e.g. mart_sales"
              />
            </div>
          </div>

          {/* Measures */}
          <MemberSection
            title="Measures"
            onAdd={() => setMeasures((rows) => [...rows, emptyMeasure()])}
          >
            {measures.map((row, i) => (
              <div key={i} className="grid grid-cols-[1fr_7rem_1fr_auto] items-end gap-2">
                <Field label="Name" htmlFor={`m-name-${i}`}>
                  <Input
                    id={`m-name-${i}`}
                    value={row.name}
                    onChange={(e) => setMeasures(update(measures, i, { name: e.target.value }))}
                    placeholder="total_amount"
                  />
                </Field>
                <Field label="Type" htmlFor={`m-type-${i}`}>
                  <Select
                    id={`m-type-${i}`}
                    value={row.type}
                    onChange={(e) =>
                      setMeasures(update(measures, i, { type: e.target.value as MeasureType }))
                    }
                  >
                    {MEASURE_TYPES.map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="Column" htmlFor={`m-sql-${i}`}>
                  <Input
                    id={`m-sql-${i}`}
                    value={row.sql}
                    onChange={(e) => setMeasures(update(measures, i, { sql: e.target.value }))}
                    placeholder={row.type === "count" ? "(optional)" : "amount"}
                  />
                </Field>
                <RemoveButton
                  label={`Remove measure ${i + 1}`}
                  onClick={() => setMeasures(removeAt(measures, i))}
                />
              </div>
            ))}
          </MemberSection>

          {/* Dimensions */}
          <MemberSection
            title="Dimensions"
            onAdd={() => setDimensions((rows) => [...rows, emptyDimension()])}
          >
            {dimensions.map((row, i) => (
              <div key={i} className="grid grid-cols-[1fr_7rem_1fr_auto] items-end gap-2">
                <Field label="Name" htmlFor={`d-name-${i}`}>
                  <Input
                    id={`d-name-${i}`}
                    value={row.name}
                    onChange={(e) => setDimensions(update(dimensions, i, { name: e.target.value }))}
                    placeholder="region"
                  />
                </Field>
                <Field label="Type" htmlFor={`d-type-${i}`}>
                  <Select
                    id={`d-type-${i}`}
                    value={row.type}
                    onChange={(e) =>
                      setDimensions(update(dimensions, i, { type: e.target.value as DimensionType }))
                    }
                  >
                    {DIMENSION_TYPES.map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="Column" htmlFor={`d-sql-${i}`}>
                  <Input
                    id={`d-sql-${i}`}
                    value={row.sql}
                    onChange={(e) => setDimensions(update(dimensions, i, { sql: e.target.value }))}
                    placeholder="region"
                  />
                </Field>
                <RemoveButton
                  label={`Remove dimension ${i + 1}`}
                  onClick={() => setDimensions(removeAt(dimensions, i))}
                />
              </div>
            ))}
          </MemberSection>

          {/* Joins (optional) */}
          <MemberSection
            title="Joins (optional)"
            onAdd={() => setJoins((rows) => [...rows, emptyJoin()])}
          >
            {joins.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                Join another model to query its members alongside this one.
              </p>
            ) : (
              joins.map((row, i) => (
                <div key={i} className="grid grid-cols-[1fr_9rem_1fr_1fr_auto] items-end gap-2">
                  <Field label="Target model" htmlFor={`j-name-${i}`}>
                    <Input
                      id={`j-name-${i}`}
                      value={row.name}
                      onChange={(e) => setJoins(update(joins, i, { name: e.target.value }))}
                      placeholder="customers"
                    />
                  </Field>
                  <Field label="Relationship" htmlFor={`j-rel-${i}`}>
                    <Select
                      id={`j-rel-${i}`}
                      value={row.relationship}
                      onChange={(e) =>
                        setJoins(
                          update(joins, i, {
                            relationship: e.target.value as SemanticJoinRelationship,
                          })
                        )
                      }
                    >
                      {JOIN_RELATIONSHIPS.map((r) => (
                        <option key={r} value={r}>
                          {r}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Field label="This column" htmlFor={`j-local-${i}`}>
                    <Input
                      id={`j-local-${i}`}
                      value={row.localKey}
                      onChange={(e) => setJoins(update(joins, i, { localKey: e.target.value }))}
                      placeholder="customer_id"
                    />
                  </Field>
                  <Field label="Target column" htmlFor={`j-foreign-${i}`}>
                    <Input
                      id={`j-foreign-${i}`}
                      value={row.foreignKey}
                      onChange={(e) => setJoins(update(joins, i, { foreignKey: e.target.value }))}
                      placeholder="id"
                    />
                  </Field>
                  <RemoveButton
                    label={`Remove join ${i + 1}`}
                    onClick={() => setJoins((rows) => rows.filter((_, j) => j !== i))}
                  />
                </div>
              ))
            )}
          </MemberSection>
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
          <DialogTitle>Delete semantic model?</DialogTitle>
          <DialogDescription>
            Charts built on it will stop resolving. This regenerates the tenant's Cube schema.
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

// --- small helpers / sub-components -----------------------------------------

function update<T>(rows: T[], index: number, patch: Partial<T>): T[] {
  return rows.map((row, i) => (i === index ? { ...row, ...patch } : row));
}

function removeAt<T>(rows: T[], index: number): T[] {
  const next = rows.filter((_, i) => i !== index);
  return next.length > 0 ? next : rows; // keep at least one row
}

function Field({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1">
      <Label htmlFor={htmlFor} className="text-xs text-muted-foreground">
        {label}
      </Label>
      {children}
    </div>
  );
}

function MemberSection({
  title,
  onAdd,
  children,
}: {
  title: string;
  onAdd: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-2 rounded-lg border bg-background/40 p-3">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-medium">{title}</h4>
        <Button type="button" variant="outline" size="sm" onClick={onAdd}>
          <Plus className="h-3.5 w-3.5" aria-hidden />
          Add
        </Button>
      </div>
      <div className="space-y-2">{children}</div>
    </div>
  );
}

function RemoveButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className="mb-1 rounded p-2 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
    >
      <Trash2 className="h-4 w-4" />
    </button>
  );
}
