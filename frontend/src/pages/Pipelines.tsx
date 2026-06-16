/**
 * Pipelines — the ETL UI (#3): manage source connections and pipelines.
 *
 * Two sections:
 *  1. Sources — create/test/delete source connections (SQL database or filesystem).
 *  2. Pipelines — create a pipeline on a source, run it now, and view run history.
 *
 * Mutations + run-now require the tenant superuser role; the backend enforces this
 * and the UI surfaces a 403 as a toast.
 */

import { useState } from "react";
import {
  CalendarClock,
  ChevronDown,
  ChevronRight,
  Database,
  Play,
  Plus,
  Trash2,
  Workflow,
} from "lucide-react";
import { toast } from "sonner";

import {
  useCreatePipeline,
  useCreateSchedule,
  useCreateSource,
  useDeletePipeline,
  useDeleteSchedule,
  useDeleteSource,
  usePipelineRuns,
  usePipelines,
  useRunPipeline,
  useSchedules,
  useSourceEngines,
  useSourceKinds,
  useSources,
  useTestSource,
} from "@/api/hooks";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Spinner } from "@/components/ui/spinner";
import { EmptyState } from "@/components/ui/empty-state";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { formatRelativeTime } from "@/lib/format";
import type {
  PipelineRunRead,
  ScheduleRead,
  SourceConnectionCreate,
  SourceConnectionRead,
} from "@/types/api";

export function Pipelines() {
  return (
    <div className="animate-in-up space-y-6">
      <PageHeader
        title="Pipelines"
        description="Connect a source, then build a pipeline that lands data in the lake and registers it to ClickHouse. Run it now or review its history."
      />
      <SourcesSection />
      <PipelinesSection />
    </div>
  );
}

function runBadgeVariant(status: string): "success" | "danger" | "info" | "secondary" {
  if (status === "success") return "success";
  if (status === "error") return "danger";
  if (status === "running" || status === "queued") return "info";
  return "secondary";
}

// ===========================================================================
// Sources
// ===========================================================================

function SourcesSection() {
  const { data: sources, isLoading } = useSources();
  const deleteSource = useDeleteSource();
  const testSource = useTestSource();
  const [open, setOpen] = useState(false);

  function handleTest(s: SourceConnectionRead) {
    testSource.mutate(s.id, {
      onSuccess: () => toast.success(`“${s.name}” is reachable`),
      onError: (err) =>
        toast.error(err instanceof Error ? err.message : "Connection test failed"),
    });
  }

  return (
    <Card className="bg-card/70">
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle className="flex items-center gap-2 text-base">
            <Database className="h-4 w-4" aria-hidden />
            Sources
          </CardTitle>
          <CardDescription>Databases and files NovaSight can read from.</CardDescription>
        </div>
        <Button size="sm" onClick={() => setOpen(true)}>
          <Plus className="h-4 w-4" aria-hidden />
          New source
        </Button>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="flex h-24 items-center justify-center">
            <Spinner label="Loading sources" />
          </div>
        ) : !sources || sources.length === 0 ? (
          <EmptyState
            icon={<Database className="h-6 w-6" />}
            title="No sources yet"
            description="Connect a SQL database or a file in object storage to build a pipeline on it."
          />
        ) : (
          <ul className="divide-y divide-border/60">
            {sources.map((s) => (
              <li key={s.id} className="flex items-center justify-between gap-3 py-2.5">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{s.name}</p>
                  <p className="truncate text-xs text-muted-foreground">{s.kind}</p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => handleTest(s)}
                    disabled={testSource.isPending}
                  >
                    Test
                  </Button>
                  <button
                    type="button"
                    onClick={() =>
                      deleteSource.mutate(s.id, {
                        onError: (err) =>
                          toast.error(err instanceof Error ? err.message : "Delete failed"),
                      })
                    }
                    aria-label={`Delete ${s.name}`}
                    className="rounded p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
      <NewSourceDialog open={open} onOpenChange={setOpen} />
    </Card>
  );
}

function NewSourceDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const { data: kinds } = useSourceKinds();
  const { data: engines } = useSourceEngines();
  const createSource = useCreateSource();

  const [name, setName] = useState("");
  const [kind, setKind] = useState("sql_database");
  // sql_database fields
  const [engine, setEngine] = useState("postgres");
  const [host, setHost] = useState("");
  const [port, setPort] = useState("");
  const [database, setDatabase] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  // filesystem fields
  const [format, setFormat] = useState("csv");
  const [key, setKey] = useState("");

  const selectedEngine = engines?.find((e) => e.key === engine);

  // Picking an engine prefills its standard port (the user can still override).
  function handleEngineChange(key: string) {
    setEngine(key);
    const spec = engines?.find((e) => e.key === key);
    if (spec) setPort(String(spec.default_port));
  }

  function buildPayload(): SourceConnectionCreate {
    if (kind === "filesystem") {
      return { name: name.trim(), kind, config: { format, key: key.trim() } };
    }
    const config: Record<string, unknown> = { engine, database: database.trim() };
    if (host.trim()) config.host = host.trim();
    if (port.trim()) config.port = Number(port);
    if (username.trim()) config.username = username.trim();
    const secret = password ? { password } : undefined;
    return { name: name.trim(), kind, config, secret };
  }

  function handleSave() {
    if (!name.trim()) {
      toast.error("A source name is required");
      return;
    }
    createSource.mutate(buildPayload(), {
      onSuccess: (s) => {
        onOpenChange(false);
        toast.success(`Created source “${s.name}”`);
      },
      onError: (err) =>
        toast.error(err instanceof Error ? err.message : "Could not create the source"),
    });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="New source">
      <DialogHeader>
        <DialogTitle>New source</DialogTitle>
        <DialogDescription>Connect a database or a file in object storage.</DialogDescription>
      </DialogHeader>

      <div className="space-y-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="src-name">Name</Label>
            <Input id="src-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. warehouse" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="src-kind">Kind</Label>
            <Select id="src-kind" value={kind} onChange={(e) => setKind(e.target.value)}>
              {(kinds ?? ["sql_database", "filesystem"]).map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </Select>
          </div>
        </div>

        {kind === "filesystem" ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="src-format">Format</Label>
              <Select id="src-format" value={format} onChange={(e) => setFormat(e.target.value)}>
                {["csv", "parquet", "json", "excel"].map((f) => (
                  <option key={f} value={f}>
                    {f}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="src-key">Object key</Label>
              <Input id="src-key" value={key} onChange={(e) => setKey(e.target.value)} placeholder="raw/orders.csv" />
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="src-engine">Engine</Label>
              <Select
                id="src-engine"
                value={engine}
                onChange={(e) => handleEngineChange(e.target.value)}
              >
                {(engines ?? []).map((eng) => (
                  <option key={eng.key} value={eng.key}>
                    {eng.label}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="src-database">{selectedEngine?.database_label ?? "Database"}</Label>
              <Input id="src-database" value={database} onChange={(e) => setDatabase(e.target.value)} placeholder="sales" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="src-host">Host</Label>
              <Input id="src-host" value={host} onChange={(e) => setHost(e.target.value)} placeholder="db.internal" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="src-port">Port</Label>
              <Input
                id="src-port"
                value={port}
                onChange={(e) => setPort(e.target.value)}
                placeholder={String(selectedEngine?.default_port ?? "")}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="src-username">Username</Label>
              <Input id="src-username" value={username} onChange={(e) => setUsername(e.target.value)} placeholder="readonly" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="src-password">Password</Label>
              <Input id="src-password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
            </div>
          </div>
        )}
      </div>

      <DialogFooter>
        <Button variant="ghost" onClick={() => onOpenChange(false)}>
          Cancel
        </Button>
        <Button onClick={handleSave} disabled={createSource.isPending}>
          {createSource.isPending ? "Creating…" : "Create source"}
        </Button>
      </DialogFooter>
    </Dialog>
  );
}

// ===========================================================================
// Pipelines
// ===========================================================================

function PipelinesSection() {
  const { data: pipelines, isLoading } = usePipelines();
  const { data: sources } = useSources();
  const { data: schedules } = useSchedules();
  const [open, setOpen] = useState(false);

  return (
    <Card className="bg-card/70">
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle className="flex items-center gap-2 text-base">
            <Workflow className="h-4 w-4" aria-hidden />
            Pipelines
          </CardTitle>
          <CardDescription>Source → Iceberg → ClickHouse.</CardDescription>
        </div>
        <Button size="sm" onClick={() => setOpen(true)} disabled={!sources || sources.length === 0}>
          <Plus className="h-4 w-4" aria-hidden />
          New pipeline
        </Button>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="flex h-24 items-center justify-center">
            <Spinner label="Loading pipelines" />
          </div>
        ) : !pipelines || pipelines.length === 0 ? (
          <EmptyState
            icon={<Workflow className="h-6 w-6" />}
            title="No pipelines yet"
            description={
              sources && sources.length > 0
                ? "Create a pipeline on one of your sources."
                : "Add a source first, then build a pipeline on it."
            }
          />
        ) : (
          <ul className="divide-y divide-border/60">
            {pipelines.map((p) => (
              <PipelineRow
                key={p.id}
                id={p.id}
                name={p.name}
                target={p.target_table}
                enabled={p.enabled}
                schedules={(schedules ?? []).filter((s) => s.target_id === p.id)}
              />
            ))}
          </ul>
        )}
      </CardContent>
      <NewPipelineDialog open={open} onOpenChange={setOpen} sources={sources ?? []} />
    </Card>
  );
}

function PipelineRow({
  id,
  name,
  target,
  enabled,
  schedules,
}: {
  id: string;
  name: string;
  target: string;
  enabled: boolean;
  schedules: ScheduleRead[];
}) {
  const runPipeline = useRunPipeline();
  const deletePipeline = useDeletePipeline();
  const [expanded, setExpanded] = useState(false);
  const [scheduleOpen, setScheduleOpen] = useState(false);
  const { data: runs, isLoading: runsLoading } = usePipelineRuns(expanded ? id : null);

  function handleRun() {
    runPipeline.mutate(id, {
      onSuccess: () => {
        setExpanded(true);
        toast.success("Run queued");
      },
      onError: (err) => toast.error(err instanceof Error ? err.message : "Could not start the run"),
    });
  }

  return (
    <li className="py-2.5">
      <div className="flex items-center justify-between gap-3">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="flex min-w-0 items-center gap-2 text-left"
          aria-expanded={expanded}
        >
          {expanded ? (
            <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
          ) : (
            <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
          )}
          <span className="min-w-0">
            <span className="block truncate text-sm font-medium">{name}</span>
            <span className="block truncate text-xs text-muted-foreground">→ {target}</span>
          </span>
        </button>
        <div className="flex shrink-0 items-center gap-2">
          {!enabled && <Badge variant="secondary">disabled</Badge>}
          {schedules.some((s) => s.enabled) && <Badge variant="info">scheduled</Badge>}
          <Button size="sm" variant="ghost" onClick={() => setScheduleOpen(true)}>
            <CalendarClock className="h-4 w-4" aria-hidden />
            Schedule
          </Button>
          <Button size="sm" variant="outline" onClick={handleRun} disabled={!enabled || runPipeline.isPending}>
            <Play className="h-4 w-4" aria-hidden />
            Run
          </Button>
          <button
            type="button"
            onClick={() =>
              deletePipeline.mutate(id, {
                onError: (err) => toast.error(err instanceof Error ? err.message : "Delete failed"),
              })
            }
            aria-label={`Delete ${name}`}
            className="rounded p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>

      {expanded && (
        <div className="mt-2 pl-6">
          {runsLoading ? (
            <Spinner label="Loading runs" />
          ) : !runs || runs.length === 0 ? (
            <p className="text-xs text-muted-foreground">No runs yet.</p>
          ) : (
            <ul className="space-y-1">
              {runs.map((r) => (
                <RunRow key={r.id} run={r} />
              ))}
            </ul>
          )}
        </div>
      )}

      <ScheduleDialog
        open={scheduleOpen}
        onOpenChange={setScheduleOpen}
        pipelineId={id}
        pipelineName={name}
        schedules={schedules}
      />
    </li>
  );
}

function ScheduleDialog({
  open,
  onOpenChange,
  pipelineId,
  pipelineName,
  schedules,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  pipelineId: string;
  pipelineName: string;
  schedules: ScheduleRead[];
}) {
  const createSchedule = useCreateSchedule();
  const deleteSchedule = useDeleteSchedule();
  const [cron, setCron] = useState("0 2 * * *");

  function handleAdd() {
    if (!cron.trim()) {
      toast.error("A cron expression is required");
      return;
    }
    createSchedule.mutate(
      { name: `${pipelineName} schedule`, target_id: pipelineId, cron: cron.trim() },
      {
        onSuccess: () => toast.success("Schedule added"),
        onError: (err) =>
          toast.error(err instanceof Error ? err.message : "Could not add the schedule"),
      }
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Schedules">
      <DialogHeader>
        <DialogTitle>Schedule “{pipelineName}”</DialogTitle>
        <DialogDescription>
          Run this pipeline automatically on a cron (5 fields: minute hour day month weekday).
        </DialogDescription>
      </DialogHeader>

      <div className="space-y-4">
        {schedules.length > 0 && (
          <ul className="divide-y divide-border/60">
            {schedules.map((s) => (
              <li key={s.id} className="flex items-center justify-between gap-3 py-2 text-sm">
                <span className="font-mono">{s.cron}</span>
                <span className="flex items-center gap-2">
                  {!s.enabled && <Badge variant="secondary">disabled</Badge>}
                  <button
                    type="button"
                    onClick={() =>
                      deleteSchedule.mutate(s.id, {
                        onError: (err) =>
                          toast.error(err instanceof Error ? err.message : "Delete failed"),
                      })
                    }
                    aria-label={`Delete schedule ${s.cron}`}
                    className="rounded p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </span>
              </li>
            ))}
          </ul>
        )}

        <div className="space-y-1.5">
          <Label htmlFor="sch-cron">New schedule (cron)</Label>
          <div className="flex gap-2">
            <Input
              id="sch-cron"
              value={cron}
              onChange={(e) => setCron(e.target.value)}
              placeholder="0 2 * * *"
              className="font-mono"
            />
            <Button onClick={handleAdd} disabled={createSchedule.isPending}>
              <Plus className="h-4 w-4" aria-hidden />
              Add
            </Button>
          </div>
        </div>
      </div>

      <DialogFooter>
        <Button variant="ghost" onClick={() => onOpenChange(false)}>
          Done
        </Button>
      </DialogFooter>
    </Dialog>
  );
}

function RunRow({ run }: { run: PipelineRunRead }) {
  return (
    <li className="flex items-center justify-between gap-3 text-xs">
      <span className="flex items-center gap-2">
        <Badge variant={runBadgeVariant(run.status)}>{run.status}</Badge>
        <span className="text-muted-foreground">{formatRelativeTime(run.created_at)}</span>
      </span>
      <span className="text-muted-foreground">
        {run.rows != null ? `${run.rows} rows` : run.error ? run.error : ""}
      </span>
    </li>
  );
}

function NewPipelineDialog({
  open,
  onOpenChange,
  sources,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  sources: SourceConnectionRead[];
}) {
  const createPipeline = useCreatePipeline();
  const [name, setName] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [object, setObject] = useState("");
  const [targetTable, setTargetTable] = useState("");

  const effectiveSourceId = sourceId || sources[0]?.id || "";

  function handleSave() {
    if (!name.trim() || !effectiveSourceId || !object.trim() || !targetTable.trim()) {
      toast.error("Name, source, object, and target table are required");
      return;
    }
    createPipeline.mutate(
      {
        name: name.trim(),
        source_connection_id: effectiveSourceId,
        config: { object: object.trim(), write_disposition: "overwrite" },
        target_table: targetTable.trim(),
      },
      {
        onSuccess: (p) => {
          onOpenChange(false);
          toast.success(`Created pipeline “${p.name}”`);
        },
        onError: (err) =>
          toast.error(err instanceof Error ? err.message : "Could not create the pipeline"),
      }
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="New pipeline">
      <DialogHeader>
        <DialogTitle>New pipeline</DialogTitle>
        <DialogDescription>Pick a source, the object to load, and a target table.</DialogDescription>
      </DialogHeader>

      <div className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="pl-name">Name</Label>
          <Input id="pl-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. orders_daily" />
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
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="pl-object">Object</Label>
            <Input id="pl-object" value={object} onChange={(e) => setObject(e.target.value)} placeholder="orders (table) or raw/orders.csv" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="pl-target">Target table</Label>
            <Input id="pl-target" value={targetTable} onChange={(e) => setTargetTable(e.target.value)} placeholder="orders" />
          </div>
        </div>
      </div>

      <DialogFooter>
        <Button variant="ghost" onClick={() => onOpenChange(false)}>
          Cancel
        </Button>
        <Button onClick={handleSave} disabled={createPipeline.isPending}>
          {createPipeline.isPending ? "Creating…" : "Create pipeline"}
        </Button>
      </DialogFooter>
    </Dialog>
  );
}
