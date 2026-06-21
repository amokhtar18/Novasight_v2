/**
 * Operations — the run & schedule control room (Phase 2, operations UIs).
 *
 * Two consolidated, cross-pipeline views the per-pipeline Ingest hub can't give:
 *  1. Schedules — every cron schedule in the tenant (shared SchedulesPanel).
 *  2. Recent runs — a live feed of runs across all pipelines (polls every 10s).
 */

import { useMemo, useState } from "react";
import { Play } from "lucide-react";

import { useRecentRuns } from "@/api/hooks";
import { PageHeader } from "@/components/layout/PageHeader";
import { SchedulesPanel } from "@/components/schedule/SchedulesPanel";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { EmptyState } from "@/components/ui/empty-state";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { formatDuration, formatRelativeTime } from "@/lib/format";
import type { PipelineRunSummary } from "@/types/api";

// Time windows for the recent-runs filter, in milliseconds (null = all time).
const WINDOWS: { value: string; label: string; ms: number | null }[] = [
  { value: "all", label: "All time", ms: null },
  { value: "1h", label: "Last hour", ms: 60 * 60_000 },
  { value: "24h", label: "Last 24 hours", ms: 24 * 60 * 60_000 },
  { value: "7d", label: "Last 7 days", ms: 7 * 24 * 60 * 60_000 },
];

function runBadgeVariant(status: string): "success" | "danger" | "info" | "secondary" {
  if (status === "success") return "success";
  if (status === "error") return "danger";
  if (status === "running" || status === "queued") return "info";
  return "secondary";
}

export function Operations() {
  return (
    <div className="animate-in-up space-y-6">
      <PageHeader
        title="Operations"
        description="Manage every schedule and watch recent pipeline runs across the workspace — without opening the orchestrator."
      />
      <SchedulesPanel />
      <RecentRunsSection />
    </div>
  );
}

function RecentRunsSection() {
  const { data: runs, isLoading, dataUpdatedAt } = useRecentRuns();

  // Filters (#2): status, pipeline, and a run-time window. Applied client-side over
  // the live feed so they stay responsive across the 10s poll without refetching.
  const [status, setStatus] = useState("all");
  const [pipeline, setPipeline] = useState("all");
  const [windowKey, setWindowKey] = useState("all");

  // Distinct pipelines present in the feed, for the pipeline filter (id → name).
  const pipelineOptions = useMemo(() => {
    const seen = new Map<string, string>();
    for (const r of runs ?? []) {
      if (!seen.has(r.pipeline_id)) seen.set(r.pipeline_id, r.pipeline_name);
    }
    return [...seen.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [runs]);

  const filtered = useMemo(() => {
    const windowMs = WINDOWS.find((w) => w.value === windowKey)?.ms ?? null;
    // Anchor the window to when the feed was last fetched (pure + refreshes with the
    // 10s poll), rather than reading the clock during render.
    const cutoff = windowMs != null ? dataUpdatedAt - windowMs : null;
    return (runs ?? []).filter((r) => {
      if (status !== "all" && r.status !== status) return false;
      if (pipeline !== "all" && r.pipeline_id !== pipeline) return false;
      if (cutoff != null) {
        const t = new Date(r.created_at).getTime();
        if (Number.isNaN(t) || t < cutoff) return false;
      }
      return true;
    });
  }, [runs, status, pipeline, windowKey, dataUpdatedAt]);

  const hasRuns = !!runs && runs.length > 0;

  return (
    <Card className="bg-card/70">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Play className="h-4 w-4" aria-hidden />
          Recent runs
        </CardTitle>
        <CardDescription>
          The latest pipeline runs across the workspace. Updates automatically.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="flex h-24 items-center justify-center">
            <Spinner label="Loading runs" />
          </div>
        ) : !hasRuns ? (
          <EmptyState
            icon={<Play className="h-6 w-6" />}
            title="No runs yet"
            description="Run a pipeline (now or on a schedule) and its history shows up here."
          />
        ) : (
          <>
            <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
              <div className="space-y-1">
                <Label htmlFor="run-status" className="text-xs text-muted-foreground">
                  Status
                </Label>
                <Select id="run-status" value={status} onChange={(e) => setStatus(e.target.value)}>
                  <option value="all">All statuses</option>
                  <option value="success">Success</option>
                  <option value="error">Error</option>
                  <option value="running">Running</option>
                  <option value="queued">Queued</option>
                </Select>
              </div>
              <div className="space-y-1">
                <Label htmlFor="run-pipeline" className="text-xs text-muted-foreground">
                  Pipeline
                </Label>
                <Select
                  id="run-pipeline"
                  value={pipeline}
                  onChange={(e) => setPipeline(e.target.value)}
                >
                  <option value="all">All pipelines</option>
                  {pipelineOptions.map(([id, name]) => (
                    <option key={id} value={id}>
                      {name}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1">
                <Label htmlFor="run-window" className="text-xs text-muted-foreground">
                  Run time
                </Label>
                <Select
                  id="run-window"
                  value={windowKey}
                  onChange={(e) => setWindowKey(e.target.value)}
                >
                  {WINDOWS.map((w) => (
                    <option key={w.value} value={w.value}>
                      {w.label}
                    </option>
                  ))}
                </Select>
              </div>
            </div>

            {filtered.length === 0 ? (
              <p className="py-6 text-center text-sm text-muted-foreground">
                No runs match these filters.
              </p>
            ) : (
              <ul className="divide-y divide-border/60">
                {filtered.map((r) => (
                  <RecentRunRow key={r.id} run={r} />
                ))}
              </ul>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

function RecentRunRow({ run }: { run: PipelineRunSummary }) {
  const duration = formatDuration(run.started_at, run.finished_at);
  return (
    <li className="flex items-center justify-between gap-3 py-2 text-sm">
      <span className="flex min-w-0 items-center gap-2">
        <Badge variant={runBadgeVariant(run.status)}>{run.status}</Badge>
        <span className="truncate font-medium">{run.pipeline_name}</span>
      </span>
      <span className="flex shrink-0 items-center gap-3 text-xs text-muted-foreground">
        <span>{run.rows != null ? `${run.rows} rows` : run.error ? run.error : ""}</span>
        {duration !== "—" && <span title="Run duration">⏱ {duration}</span>}
        <span>{formatRelativeTime(run.created_at)}</span>
      </span>
    </li>
  );
}
