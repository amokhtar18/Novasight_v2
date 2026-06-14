/**
 * Operations — the run & schedule control room (Phase 2, operations UIs).
 *
 * Two consolidated, cross-pipeline views the per-pipeline Pipelines page can't give:
 *  1. Schedules — every cron schedule in the tenant, with pause/resume + delete.
 *  2. Recent runs — a live feed of runs across all pipelines (polls every 10s).
 *
 * Mutations (pause/resume, delete) require the tenant superuser role; the backend
 * enforces it and the UI hides those controls for non-superusers (and surfaces a
 * 403 as a toast if the backend rejects a call anyway).
 */

import {
  CalendarClock,
  Pause,
  Play,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";

import {
  useDeleteSchedule,
  usePipelines,
  useRecentRuns,
  useSchedules,
  useUpdateSchedule,
} from "@/api/hooks";
import { useIdentity } from "@/lib/identity";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Spinner } from "@/components/ui/spinner";
import { EmptyState } from "@/components/ui/empty-state";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { formatRelativeTime } from "@/lib/format";
import type { PipelineRunSummary, ScheduleRead } from "@/types/api";

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
      <SchedulesSection />
      <RecentRunsSection />
    </div>
  );
}

// ===========================================================================
// Schedules
// ===========================================================================

function SchedulesSection() {
  const { data: schedules, isLoading } = useSchedules();
  const { data: pipelines } = usePipelines();
  const { isSuperuser } = useIdentity();

  const pipelineName = (id: string): string =>
    pipelines?.find((p) => p.id === id)?.name ?? "unknown pipeline";

  return (
    <Card className="bg-card/70">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <CalendarClock className="h-4 w-4" aria-hidden />
          Schedules
        </CardTitle>
        <CardDescription>
          Cron schedules that run pipelines automatically. Create them from a pipeline; pause
          or remove them here.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="flex h-24 items-center justify-center">
            <Spinner label="Loading schedules" />
          </div>
        ) : !schedules || schedules.length === 0 ? (
          <EmptyState
            icon={<CalendarClock className="h-6 w-6" />}
            title="No schedules yet"
            description="Open a pipeline and add a schedule to run it on a cadence."
          />
        ) : (
          <ul className="divide-y divide-border/60">
            {schedules.map((s) => (
              <ScheduleRow
                key={s.id}
                schedule={s}
                pipelineName={pipelineName(s.target_id)}
                canManage={isSuperuser}
              />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function ScheduleRow({
  schedule,
  pipelineName,
  canManage,
}: {
  schedule: ScheduleRead;
  pipelineName: string;
  canManage: boolean;
}) {
  const updateSchedule = useUpdateSchedule();
  const deleteSchedule = useDeleteSchedule();

  function handleToggle() {
    updateSchedule.mutate(
      { id: schedule.id, patch: { enabled: !schedule.enabled } },
      {
        onSuccess: () =>
          toast.success(schedule.enabled ? "Schedule paused" : "Schedule resumed"),
        onError: (err) =>
          toast.error(err instanceof Error ? err.message : "Could not update the schedule"),
      }
    );
  }

  return (
    <li className="flex items-center justify-between gap-3 py-2.5">
      <div className="min-w-0">
        <p className="truncate text-sm font-medium">{schedule.name}</p>
        <p className="truncate text-xs text-muted-foreground">
          <span className="font-mono">{schedule.cron}</span> · {pipelineName}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {!schedule.enabled && <Badge variant="secondary">paused</Badge>}
        {canManage && (
          <>
            <Button
              size="sm"
              variant="ghost"
              onClick={handleToggle}
              disabled={updateSchedule.isPending}
            >
              {schedule.enabled ? (
                <>
                  <Pause className="h-4 w-4" aria-hidden />
                  Pause
                </>
              ) : (
                <>
                  <Play className="h-4 w-4" aria-hidden />
                  Resume
                </>
              )}
            </Button>
            <button
              type="button"
              onClick={() =>
                deleteSchedule.mutate(schedule.id, {
                  onError: (err) =>
                    toast.error(err instanceof Error ? err.message : "Delete failed"),
                })
              }
              aria-label={`Delete schedule ${schedule.name}`}
              className="rounded p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </>
        )}
      </div>
    </li>
  );
}

// ===========================================================================
// Recent runs
// ===========================================================================

function RecentRunsSection() {
  const { data: runs, isLoading } = useRecentRuns();

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
        ) : !runs || runs.length === 0 ? (
          <EmptyState
            icon={<Play className="h-6 w-6" />}
            title="No runs yet"
            description="Run a pipeline (now or on a schedule) and its history shows up here."
          />
        ) : (
          <ul className="divide-y divide-border/60">
            {runs.map((r) => (
              <RecentRunRow key={r.id} run={r} />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function RecentRunRow({ run }: { run: PipelineRunSummary }) {
  return (
    <li className="flex items-center justify-between gap-3 py-2 text-sm">
      <span className="flex min-w-0 items-center gap-2">
        <Badge variant={runBadgeVariant(run.status)}>{run.status}</Badge>
        <span className="truncate font-medium">{run.pipeline_name}</span>
      </span>
      <span className="flex shrink-0 items-center gap-3 text-xs text-muted-foreground">
        <span>{run.rows != null ? `${run.rows} rows` : run.error ? run.error : ""}</span>
        <span>{formatRelativeTime(run.created_at)}</span>
      </span>
    </li>
  );
}
