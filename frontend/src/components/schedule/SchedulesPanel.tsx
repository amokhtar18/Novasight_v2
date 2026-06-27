/**
 * SchedulesPanel — central management for reusable cron schedules (#3).
 *
 * A schedule is a named cron that can drive *one or more* pipelines (M:N). This panel
 * is the single place to create one, attach/detach pipelines, pause/resume, and delete
 * it — reused by the Ingest hub's "Schedules" tab and the Operations monitor. Mutations
 * require the tenant superuser role; non-superusers see a read-only list (the backend
 * enforces it too).
 */

import { useState } from "react";
import { CalendarClock, Pause, Pencil, Play, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import {
  useCreateSchedule,
  useDeleteSchedule,
  usePipelines,
  useSchedules,
  useUpdateSchedule,
} from "@/api/hooks";
import { useIdentity } from "@/lib/identity";
import { CronBuilder } from "@/components/schedule/CronBuilder";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/ui/spinner";
import { EmptyState } from "@/components/ui/empty-state";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { PipelineRead, ScheduleRead } from "@/types/api";

export function SchedulesPanel() {
  const { data: schedules, isLoading } = useSchedules();
  const { data: pipelines } = usePipelines();
  const { isSuperuser } = useIdentity();
  // null = closed; { schedule: null } = create; { schedule } = edit.
  const [dialog, setDialog] = useState<{ schedule: ScheduleRead | null } | null>(null);

  const pipelineName = (id: string): string =>
    pipelines?.find((p) => p.id === id)?.name ?? "unknown pipeline";
  const hasPipelines = !!pipelines && pipelines.length > 0;

  return (
    <Card className="bg-card/70">
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle className="flex items-center gap-2 text-base">
            <CalendarClock className="h-4 w-4" aria-hidden />
            Schedules
          </CardTitle>
          <CardDescription>
            Reusable cron schedules. Create one and attach it to any pipelines; pause or
            remove it here.
          </CardDescription>
        </div>
        {isSuperuser && (
          <Button
            size="sm"
            onClick={() => setDialog({ schedule: null })}
            disabled={!hasPipelines}
            title={hasPipelines ? undefined : "Create a pipeline first"}
          >
            <Plus className="h-4 w-4" aria-hidden />
            New schedule
          </Button>
        )}
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
            description={
              isSuperuser
                ? "Create a schedule and attach it to one or more pipelines."
                : "A workspace admin can create schedules here."
            }
          />
        ) : (
          <ul className="divide-y divide-border/60">
            {schedules.map((s) => (
              <ScheduleRow
                key={s.id}
                schedule={s}
                pipelineNames={s.pipeline_ids.map(pipelineName)}
                canManage={isSuperuser}
                onEdit={() => setDialog({ schedule: s })}
              />
            ))}
          </ul>
        )}
      </CardContent>

      {isSuperuser && (
        <ScheduleFormDialog
          key={dialog?.schedule?.id ?? "new"}
          open={dialog !== null}
          editing={dialog?.schedule ?? null}
          pipelines={pipelines ?? []}
          onOpenChange={(o) => setDialog(o ? dialog : null)}
        />
      )}
    </Card>
  );
}

function ScheduleRow({
  schedule,
  pipelineNames,
  canManage,
  onEdit,
}: {
  schedule: ScheduleRead;
  pipelineNames: string[];
  canManage: boolean;
  onEdit: () => void;
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
          <span className="font-mono">{schedule.cron}</span> ·{" "}
          {pipelineNames.length > 0 ? pipelineNames.join(", ") : "no pipelines"}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <Badge variant="secondary">
          {schedule.pipeline_ids.length} pipeline{schedule.pipeline_ids.length === 1 ? "" : "s"}
        </Badge>
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
              onClick={onEdit}
              aria-label={`Edit schedule ${schedule.name}`}
              className="rounded p-1.5 text-muted-foreground hover:bg-primary/10 hover:text-primary"
            >
              <Pencil className="h-4 w-4" />
            </button>
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

function ScheduleFormDialog({
  open,
  onOpenChange,
  editing,
  pipelines,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  editing: ScheduleRead | null;
  pipelines: PipelineRead[];
}) {
  const isEdit = !!editing;
  const createSchedule = useCreateSchedule();
  const updateSchedule = useUpdateSchedule();

  const [name, setName] = useState(editing?.name ?? "");
  const [cron, setCron] = useState(editing?.cron ?? "0 2 * * *");
  const [selected, setSelected] = useState<string[]>(editing?.pipeline_ids ?? []);
  const pending = createSchedule.isPending || updateSchedule.isPending;

  function toggle(id: string) {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((p) => p !== id) : [...prev, id]
    );
  }

  function handleSave() {
    if (!name.trim()) {
      toast.error("A schedule name is required");
      return;
    }
    if (selected.length === 0) {
      toast.error("Attach at least one pipeline");
      return;
    }
    if (isEdit && editing) {
      updateSchedule.mutate(
        { id: editing.id, patch: { name: name.trim(), cron: cron.trim(), pipeline_ids: selected } },
        {
          onSuccess: () => {
            onOpenChange(false);
            toast.success("Schedule updated");
          },
          onError: (err) =>
            toast.error(err instanceof Error ? err.message : "Could not update the schedule"),
        }
      );
      return;
    }
    createSchedule.mutate(
      { name: name.trim(), cron: cron.trim(), pipeline_ids: selected },
      {
        onSuccess: () => {
          onOpenChange(false);
          toast.success("Schedule created");
        },
        onError: (err) =>
          toast.error(err instanceof Error ? err.message : "Could not create the schedule"),
      }
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Schedule">
      <DialogHeader>
        <DialogTitle>{isEdit ? "Edit schedule" : "New schedule"}</DialogTitle>
        <DialogDescription>
          Name it, set the cron cadence, and choose which pipelines it runs.
        </DialogDescription>
      </DialogHeader>

      <div className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="sched-name">Name</Label>
          <Input
            id="sched-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Nightly refresh"
          />
        </div>

        <div className="space-y-1.5">
          <Label>Cadence</Label>
          <CronBuilder value={cron} onChange={setCron} />
        </div>

        <div className="space-y-1.5">
          <Label>Pipelines</Label>
          <div className="max-h-44 space-y-1 overflow-y-auto rounded-md border p-2">
            {pipelines.length === 0 ? (
              <p className="px-1 py-2 text-xs text-muted-foreground">No pipelines to attach yet.</p>
            ) : (
              pipelines.map((p) => (
                <label
                  key={p.id}
                  className="flex cursor-pointer items-center gap-2 rounded px-1 py-1 text-sm hover:bg-accent/40"
                >
                  <Checkbox
                    checked={selected.includes(p.id)}
                    onChange={() => toggle(p.id)}
                    aria-label={`Attach ${p.name}`}
                  />
                  <span className="truncate">{p.name}</span>
                  <span className="ml-auto truncate text-xs text-muted-foreground">
                    → {p.target_table}
                  </span>
                </label>
              ))
            )}
          </div>
          <p className="text-xs text-muted-foreground">
            {selected.length} pipeline{selected.length === 1 ? "" : "s"} selected.
          </p>
        </div>
      </div>

      <DialogFooter>
        <Button variant="ghost" onClick={() => onOpenChange(false)}>
          Cancel
        </Button>
        <Button onClick={handleSave} disabled={pending}>
          {pending ? "Saving…" : isEdit ? "Save schedule" : "Create schedule"}
        </Button>
      </DialogFooter>
    </Dialog>
  );
}
