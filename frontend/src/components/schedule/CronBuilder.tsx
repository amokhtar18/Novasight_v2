/**
 * CronBuilder — build a 5-field cron from presets, or hand-write one (#9).
 *
 * Most users think "every day at 02:00", not "0 2 * * *". The Preset mode turns
 * a frequency + time into a cron string; Advanced mode exposes the raw expression
 * for power users. Either way the component is controlled — it emits the cron via
 * `onChange`, and `describeCron` renders a plain-English summary of the result.
 *
 * The backend still validates the 5-field expression (schemas/schedule.py), so this
 * is convenience, not the source of truth.
 */

import { useState } from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";

export type Frequency = "hourly" | "daily" | "weekly" | "monthly";

export interface CronParts {
  frequency: Frequency;
  minute: number;
  hour: number;
  weekday: number; // 0=Sun … 6=Sat
  dom: number; // day of month, 1–31
}

const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

const DEFAULT_PARTS: CronParts = {
  frequency: "daily",
  minute: 0,
  hour: 2,
  weekday: 1,
  dom: 1,
};

/** Build a 5-field cron (minute hour day-of-month month day-of-week) from parts. */
export function cronFromParts(p: CronParts): string {
  const m = clamp(p.minute, 0, 59);
  const h = clamp(p.hour, 0, 23);
  switch (p.frequency) {
    case "hourly":
      return `${m} * * * *`;
    case "daily":
      return `${m} ${h} * * *`;
    case "weekly":
      return `${m} ${h} * * ${clamp(p.weekday, 0, 6)}`;
    case "monthly":
      return `${m} ${h} ${clamp(p.dom, 1, 31)} * *`;
  }
}

/** A plain-English summary of a 5-field cron (falls back to the raw expression). */
export function describeCron(cron: string): string {
  const f = cron.trim().split(/\s+/);
  if (f.length !== 5) return `Custom schedule: ${cron}`;
  const [min, hour, dom, mon, dow] = f;
  const time = (h: string, m: string) =>
    `${h.padStart(2, "0")}:${m.padStart(2, "0")}`;
  if (mon === "*" && dom === "*" && dow === "*" && hour === "*" && /^\d+$/.test(min))
    return `Every hour at :${min.padStart(2, "0")}`;
  if (mon === "*" && dom === "*" && dow === "*" && /^\d+$/.test(hour) && /^\d+$/.test(min))
    return `Every day at ${time(hour, min)}`;
  if (mon === "*" && dom === "*" && /^\d+$/.test(dow) && /^\d+$/.test(hour))
    return `Every ${WEEKDAYS[Number(dow)] ?? dow} at ${time(hour, min)}`;
  if (mon === "*" && dow === "*" && /^\d+$/.test(dom) && /^\d+$/.test(hour))
    return `Monthly on day ${dom} at ${time(hour, min)}`;
  return `Custom schedule: ${cron}`;
}

function clamp(n: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, Number.isFinite(n) ? n : lo));
}

export function CronBuilder({
  value,
  onChange,
}: {
  value: string;
  onChange: (cron: string) => void;
}) {
  const [mode, setMode] = useState<"preset" | "advanced">("preset");
  const [parts, setParts] = useState<CronParts>(DEFAULT_PARTS);

  function setPart(patch: Partial<CronParts>) {
    const next = { ...parts, ...patch };
    setParts(next);
    onChange(cronFromParts(next));
  }

  function switchMode(m: "preset" | "advanced") {
    setMode(m);
    if (m === "preset") onChange(cronFromParts(parts));
  }

  return (
    <div className="space-y-3">
      <div className="flex gap-1 rounded-md bg-muted/50 p-0.5 text-sm">
        {(["preset", "advanced"] as const).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => switchMode(m)}
            className={
              "flex-1 rounded px-2 py-1 capitalize transition-colors " +
              (mode === m ? "bg-background font-medium shadow-sm" : "text-muted-foreground")
            }
          >
            {m}
          </button>
        ))}
      </div>

      {mode === "preset" ? (
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="cb-frequency">Frequency</Label>
            <Select
              id="cb-frequency"
              value={parts.frequency}
              onChange={(e) => setPart({ frequency: e.target.value as Frequency })}
            >
              <option value="hourly">Hourly</option>
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
              <option value="monthly">Monthly</option>
            </Select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            {parts.frequency === "weekly" && (
              <div className="space-y-1.5">
                <Label htmlFor="cb-weekday">Day of week</Label>
                <Select
                  id="cb-weekday"
                  value={String(parts.weekday)}
                  onChange={(e) => setPart({ weekday: Number(e.target.value) })}
                >
                  {WEEKDAYS.map((d, i) => (
                    <option key={d} value={i}>
                      {d}
                    </option>
                  ))}
                </Select>
              </div>
            )}
            {parts.frequency === "monthly" && (
              <div className="space-y-1.5">
                <Label htmlFor="cb-dom">Day of month</Label>
                <Input
                  id="cb-dom"
                  type="number"
                  min={1}
                  max={31}
                  value={parts.dom}
                  onChange={(e) => setPart({ dom: Number(e.target.value) })}
                />
              </div>
            )}
            {parts.frequency !== "hourly" && (
              <div className="space-y-1.5">
                <Label htmlFor="cb-hour">Hour</Label>
                <Input
                  id="cb-hour"
                  type="number"
                  min={0}
                  max={23}
                  value={parts.hour}
                  onChange={(e) => setPart({ hour: Number(e.target.value) })}
                />
              </div>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="cb-minute">Minute</Label>
              <Input
                id="cb-minute"
                type="number"
                min={0}
                max={59}
                value={parts.minute}
                onChange={(e) => setPart({ minute: Number(e.target.value) })}
              />
            </div>
          </div>
        </div>
      ) : (
        <div className="space-y-1.5">
          <Label htmlFor="sch-cron">Cron expression</Label>
          <Input
            id="sch-cron"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder="0 2 * * *"
            className="font-mono"
          />
        </div>
      )}

      <p className="text-xs text-muted-foreground">
        {describeCron(value)} <span className="font-mono">({value})</span>
      </p>
    </div>
  );
}
