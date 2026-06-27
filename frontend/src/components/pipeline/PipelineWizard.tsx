/**
 * PipelineWizard — the field-level "design a pipeline" flow (#5/#6/#7).
 *
 * For a SQL source it walks: Details → Schema/Table → Fields → Load mode → Review,
 * driving the schema → table → columns drill-down off `POST /sources/{id}/introspect`
 * and defaulting each column's destination type from the backend suggestion. The user
 * picks included columns, renames/retypes them, sets the primary key, partition,
 * source-side filters, and the SCD/CDC load mode. For a non-SQL source it collapses to
 * the original "object + target" form.
 *
 * The whole config is assembled into one PipelineCreate posted on the final step. The
 * structured filter (column/operator/value) is never raw SQL — see schemas/pipeline.py.
 */

import { useMemo, useState } from "react";
import { toast } from "sonner";

import { useCreatePipeline, useIntrospectSource } from "@/api/hooks";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import type {
  ColumnMap,
  FilterClause,
  FilterOperator,
  PipelineConfig,
  ScdType,
  SourceConnectionRead,
  TargetType,
  WriteDisposition,
} from "@/types/api";

const TARGET_TYPES: TargetType[] = [
  "String",
  "Int64",
  "Float64",
  "Decimal",
  "Boolean",
  "Date",
  "DateTime",
  "JSON",
  "UUID",
];

const OPERATORS: FilterOperator[] = [
  "eq",
  "ne",
  "gt",
  "ge",
  "lt",
  "le",
  "like",
  "in",
  "is_null",
  "is_not_null",
];

/** Local, editable view of one source column. */
interface FieldEdit {
  source_name: string;
  source_type: string;
  target_name: string;
  target_type: TargetType;
  included: boolean;
}

interface FilterRow {
  column: string;
  operator: FilterOperator;
  value: string;
}

const SQL_KINDS = new Set(["sql_database"]);

export function PipelineWizard({
  open,
  onOpenChange,
  sources,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  sources: SourceConnectionRead[];
}) {
  const createPipeline = useCreatePipeline();
  const introspect = useIntrospectSource();

  const [step, setStep] = useState(0);
  const [name, setName] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [targetTable, setTargetTable] = useState("");

  // Schema/table drill-down.
  const [schemas, setSchemas] = useState<string[]>([]);
  const [tables, setTables] = useState<string[]>([]);
  const [schema, setSchema] = useState("");
  const [table, setTable] = useState("");
  // Non-SQL sources: a free-text object key.
  const [objectKey, setObjectKey] = useState("");

  // Field map + load options.
  const [fields, setFields] = useState<FieldEdit[]>([]);
  const [writeDisposition, setWriteDisposition] = useState<WriteDisposition>("overwrite");
  const [scdType, setScdType] = useState<ScdType>("none");
  const [cdcColumn, setCdcColumn] = useState("");
  const [primaryKey, setPrimaryKey] = useState<string[]>([]);
  const [partitionBy, setPartitionBy] = useState<string[]>([]);
  const [filters, setFilters] = useState<FilterRow[]>([]);

  const effectiveSourceId = sourceId || sources[0]?.id || "";
  const source = sources.find((s) => s.id === effectiveSourceId);
  const isSql = source ? SQL_KINDS.has(source.kind) : true;
  const includedFields = useMemo(() => fields.filter((f) => f.included), [fields]);

  function reset() {
    setStep(0);
    setName("");
    setSourceId("");
    setTargetTable("");
    setSchemas([]);
    setTables([]);
    setSchema("");
    setTable("");
    setObjectKey("");
    setFields([]);
    setWriteDisposition("overwrite");
    setScdType("none");
    setCdcColumn("");
    setPrimaryKey([]);
    setPartitionBy([]);
    setFilters([]);
  }

  function close(o: boolean) {
    if (!o) reset();
    onOpenChange(o);
  }

  async function loadSchemas() {
    if (!effectiveSourceId) return;
    try {
      const res = await introspect.mutateAsync({ id: effectiveSourceId });
      setSchemas(res.schemas);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not list schemas");
    }
  }

  async function loadTables(s: string) {
    setSchema(s);
    setTable("");
    setTables([]);
    if (!s) return;
    try {
      const res = await introspect.mutateAsync({ id: effectiveSourceId, schema: s });
      setTables(res.tables);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not list tables");
    }
  }

  async function loadColumns(t: string) {
    setTable(t);
    if (!targetTable) setTargetTable(t);
    if (!t) return;
    try {
      const res = await introspect.mutateAsync({
        id: effectiveSourceId,
        schema: schema || undefined,
        table: t,
      });
      setFields(
        res.columns.map((c) => ({
          source_name: c.name,
          source_type: c.source_type,
          target_name: c.name,
          target_type: c.suggested_target_type,
          included: true,
        }))
      );
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not read columns");
    }
  }

  function patchField(srcName: string, patch: Partial<FieldEdit>) {
    setFields((fs) => fs.map((f) => (f.source_name === srcName ? { ...f, ...patch } : f)));
  }

  function toggleIn(list: string[], value: string): string[] {
    return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
  }

  function buildConfig(): PipelineConfig {
    const columns: ColumnMap[] = fields.map((f) => ({
      source_name: f.source_name,
      source_type: f.source_type,
      target_name: f.target_name,
      target_type: f.target_type,
      included: f.included,
    }));
    const sourceFilters: FilterClause[] = filters
      .filter((f) => f.column)
      .map((f) => {
        const nullary = f.operator === "is_null" || f.operator === "is_not_null";
        const value = nullary
          ? null
          : f.operator === "in"
            ? f.value.split(",").map((v) => v.trim()).filter(Boolean)
            : f.value;
        return { column: f.column, operator: f.operator, value };
      });
    return {
      object: isSql ? table : objectKey.trim(),
      ...(isSql && schema ? { source_schema: schema } : {}),
      write_disposition: writeDisposition,
      ...(isSql ? { columns } : {}),
      primary_key: primaryKey,
      partition_by: partitionBy,
      source_filters: sourceFilters,
      scd_type: scdType,
      ...(cdcColumn ? { cdc_column: cdcColumn } : {}),
    };
  }

  function handleCreate() {
    const obj = isSql ? table : objectKey.trim();
    if (!name.trim() || !effectiveSourceId || !obj || !targetTable.trim()) {
      toast.error("Name, source, object, and target table are required");
      return;
    }
    if ((writeDisposition === "merge" || scdType !== "none") && primaryKey.length === 0) {
      toast.error("Merge / SCD load needs at least one primary-key column");
      return;
    }
    if (writeDisposition === "incremental" && !cdcColumn) {
      toast.error("Incremental load needs a CDC column");
      return;
    }
    createPipeline.mutate(
      {
        name: name.trim(),
        source_connection_id: effectiveSourceId,
        config: buildConfig(),
        target_table: targetTable.trim(),
      },
      {
        onSuccess: (p) => {
          close(false);
          toast.success(`Created pipeline “${p.name}”`);
        },
        onError: (err) =>
          toast.error(err instanceof Error ? err.message : "Could not create the pipeline"),
      }
    );
  }

  // Steps differ for SQL vs. file sources.
  const steps = isSql
    ? ["Details", "Schema & table", "Fields", "Load mode", "Review"]
    : ["Details", "Review"];
  const lastStep = steps.length - 1;

  function next() {
    // Trigger introspection as the user advances into the relevant step.
    if (isSql && step === 0) void loadSchemas();
    if (isSql && step === 1) void loadColumns(table);
    setStep((s) => Math.min(s + 1, lastStep));
  }

  return (
    <Dialog open={open} onOpenChange={close} title="New pipeline">
      <DialogHeader>
        <DialogTitle>New pipeline</DialogTitle>
        <DialogDescription>
          {steps.map((label, i) => (
            <span key={label} className={i === step ? "font-medium text-foreground" : ""}>
              {i > 0 ? " · " : ""}
              {label}
            </span>
          ))}
        </DialogDescription>
      </DialogHeader>

      <div className="max-h-[60vh] space-y-4 overflow-y-auto pr-1">
        {step === 0 && (
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="pl-name">Name</Label>
              <Input id="pl-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="orders_daily" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pl-source">Source</Label>
              <Select id="pl-source" value={effectiveSourceId} onChange={(e) => setSourceId(e.target.value)}>
                {sources.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} ({s.kind})
                  </option>
                ))}
              </Select>
            </div>
            {!isSql && (
              <div className="space-y-1.5">
                <Label htmlFor="pl-object">Object</Label>
                <Input id="pl-object" value={objectKey} onChange={(e) => setObjectKey(e.target.value)} placeholder="raw/orders.csv" />
              </div>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="pl-target">Target table</Label>
              <Input id="pl-target" value={targetTable} onChange={(e) => setTargetTable(e.target.value)} placeholder="orders" />
            </div>
          </div>
        )}

        {isSql && step === 1 && (
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="pl-schema">Schema</Label>
              <Select id="pl-schema" value={schema} onChange={(e) => void loadTables(e.target.value)}>
                <option value="">Select a schema…</option>
                {schemas.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pl-table">Table</Label>
              <Select id="pl-table" value={table} onChange={(e) => setTable(e.target.value)} disabled={!schema}>
                <option value="">Select a table…</option>
                {tables.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </Select>
            </div>
          </div>
        )}

        {isSql && step === 2 && (
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">
              Pick the columns to load and their destination type.
            </p>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground">
                  <th className="pb-1 font-medium">Use</th>
                  <th className="pb-1 font-medium">Source</th>
                  <th className="pb-1 font-medium">Target name</th>
                  <th className="pb-1 font-medium">Type</th>
                </tr>
              </thead>
              <tbody>
                {fields.map((f) => (
                  <tr key={f.source_name} className="border-t border-border/50">
                    <td className="py-1.5">
                      <Checkbox
                        aria-label={`Include ${f.source_name}`}
                        checked={f.included}
                        onChange={(e) => patchField(f.source_name, { included: e.target.checked })}
                      />
                    </td>
                    <td className="py-1.5">
                      <span className="font-mono text-xs">{f.source_name}</span>
                      <span className="ml-1 text-[0.65rem] text-muted-foreground">{f.source_type}</span>
                    </td>
                    <td className="py-1.5 pr-2">
                      <Input
                        aria-label={`Target name for ${f.source_name}`}
                        value={f.target_name}
                        onChange={(e) => patchField(f.source_name, { target_name: e.target.value })}
                        className="h-7"
                      />
                    </td>
                    <td className="py-1.5">
                      <Select
                        aria-label={`Target type for ${f.source_name}`}
                        value={f.target_type}
                        onChange={(e) => patchField(f.source_name, { target_type: e.target.value as TargetType })}
                        className="h-7"
                      >
                        {TARGET_TYPES.map((t) => (
                          <option key={t} value={t}>
                            {t}
                          </option>
                        ))}
                      </Select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {isSql && step === 3 && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="pl-mode">Load mode</Label>
                <Select id="pl-mode" value={writeDisposition} onChange={(e) => setWriteDisposition(e.target.value as WriteDisposition)}>
                  <option value="overwrite">Full overwrite</option>
                  <option value="append">Append</option>
                  <option value="merge">Merge (upsert)</option>
                  <option value="incremental">Incremental (CDC)</option>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="pl-scd">SCD type</Label>
                <Select id="pl-scd" value={scdType} onChange={(e) => setScdType(e.target.value as ScdType)}>
                  <option value="none">None</option>
                  <option value="scd1">Type 1 (overwrite)</option>
                  <option value="scd2">Type 2 (history)</option>
                </Select>
              </div>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="pl-cdc">CDC / change column</Label>
              <Select id="pl-cdc" value={cdcColumn} onChange={(e) => setCdcColumn(e.target.value)}>
                <option value="">None</option>
                {includedFields.map((f) => (
                  <option key={f.source_name} value={f.source_name}>
                    {f.source_name}
                  </option>
                ))}
              </Select>
            </div>

            <fieldset className="space-y-1.5">
              <legend className="text-sm font-medium">Primary key</legend>
              <div className="flex flex-wrap gap-2">
                {includedFields.map((f) => (
                  <label key={f.target_name} className="flex items-center gap-1.5 text-xs">
                    <Checkbox
                      aria-label={`Primary key ${f.target_name}`}
                      checked={primaryKey.includes(f.target_name)}
                      onChange={() => setPrimaryKey((pk) => toggleIn(pk, f.target_name))}
                    />
                    <span className="font-mono">{f.target_name}</span>
                  </label>
                ))}
              </div>
            </fieldset>

            <fieldset className="space-y-1.5">
              <legend className="text-sm font-medium">Partition by</legend>
              <div className="flex flex-wrap gap-2">
                {includedFields.map((f) => (
                  <label key={f.target_name} className="flex items-center gap-1.5 text-xs">
                    <Checkbox
                      aria-label={`Partition by ${f.target_name}`}
                      checked={partitionBy.includes(f.target_name)}
                      onChange={() => setPartitionBy((p) => toggleIn(p, f.target_name))}
                    />
                    <span className="font-mono">{f.target_name}</span>
                  </label>
                ))}
              </div>
            </fieldset>

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label>Source filters</Label>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={() => setFilters((fl) => [...fl, { column: "", operator: "eq", value: "" }])}
                >
                  Add filter
                </Button>
              </div>
              {filters.map((f, i) => {
                const nullary = f.operator === "is_null" || f.operator === "is_not_null";
                return (
                  <div key={i} className="flex items-center gap-2">
                    <Select
                      aria-label={`Filter column ${i + 1}`}
                      value={f.column}
                      onChange={(e) => setFilters((fl) => fl.map((x, j) => (j === i ? { ...x, column: e.target.value } : x)))}
                      className="h-7"
                    >
                      <option value="">column…</option>
                      {includedFields.map((c) => (
                        <option key={c.source_name} value={c.source_name}>
                          {c.source_name}
                        </option>
                      ))}
                    </Select>
                    <Select
                      aria-label={`Filter operator ${i + 1}`}
                      value={f.operator}
                      onChange={(e) => setFilters((fl) => fl.map((x, j) => (j === i ? { ...x, operator: e.target.value as FilterOperator } : x)))}
                      className="h-7 w-24"
                    >
                      {OPERATORS.map((op) => (
                        <option key={op} value={op}>
                          {op}
                        </option>
                      ))}
                    </Select>
                    {!nullary && (
                      <Input
                        aria-label={`Filter value ${i + 1}`}
                        value={f.value}
                        onChange={(e) => setFilters((fl) => fl.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))}
                        placeholder={f.operator === "in" ? "a, b, c" : "value"}
                        className="h-7"
                      />
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {step === lastStep && (
          <div className="space-y-2 text-sm">
            <Row label="Name" value={name || "—"} />
            <Row label="Source" value={source ? `${source.name} (${source.kind})` : "—"} />
            <Row label="Object" value={isSql ? `${schema ? schema + "." : ""}${table}` : objectKey} />
            <Row label="Target table" value={targetTable || "—"} />
            <Row label="Load mode" value={writeDisposition} />
            {scdType !== "none" && <Row label="SCD" value={scdType} />}
            {cdcColumn && <Row label="CDC column" value={cdcColumn} />}
            {primaryKey.length > 0 && <Row label="Primary key" value={primaryKey.join(", ")} />}
            {partitionBy.length > 0 && <Row label="Partition by" value={partitionBy.join(", ")} />}
            {isSql && <Row label="Columns" value={`${includedFields.length} of ${fields.length} included`} />}
          </div>
        )}
      </div>

      <DialogFooter>
        {step > 0 && (
          <Button variant="ghost" onClick={() => setStep((s) => Math.max(0, s - 1))}>
            Back
          </Button>
        )}
        {step < lastStep ? (
          <Button onClick={next}>Next</Button>
        ) : (
          <Button onClick={handleCreate} disabled={createPipeline.isPending}>
            {createPipeline.isPending ? "Creating…" : "Create pipeline"}
          </Button>
        )}
      </DialogFooter>
    </Dialog>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4">
      <span className="text-muted-foreground">{label}</span>
      <span className="truncate text-right font-medium">{value}</span>
    </div>
  );
}
