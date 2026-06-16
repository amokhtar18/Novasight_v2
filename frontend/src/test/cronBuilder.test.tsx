/**
 * Tests for the schedule cron builder (#9) — pure cron generation/description
 * and the preset → cron emission through the component.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { CronBuilder, cronFromParts, describeCron, type CronParts } from "@/components/schedule/CronBuilder";

const base: CronParts = { frequency: "daily", minute: 0, hour: 2, weekday: 1, dom: 1 };

describe("cronFromParts", () => {
  it("builds a cron per frequency", () => {
    expect(cronFromParts({ ...base, frequency: "hourly", minute: 15 })).toBe("15 * * * *");
    expect(cronFromParts({ ...base, frequency: "daily", hour: 6, minute: 30 })).toBe("30 6 * * *");
    expect(cronFromParts({ ...base, frequency: "weekly", weekday: 5, hour: 9 })).toBe("0 9 * * 5");
    expect(cronFromParts({ ...base, frequency: "monthly", dom: 15, hour: 1 })).toBe("0 1 15 * *");
  });

  it("clamps out-of-range parts", () => {
    expect(cronFromParts({ ...base, frequency: "hourly", minute: 99 })).toBe("59 * * * *");
  });
});

describe("describeCron", () => {
  it("summarises common patterns", () => {
    expect(describeCron("15 * * * *")).toBe("Every hour at :15");
    expect(describeCron("30 6 * * *")).toBe("Every day at 06:30");
    expect(describeCron("0 9 * * 5")).toBe("Every Friday at 09:00");
    expect(describeCron("0 1 15 * *")).toBe("Monthly on day 15 at 01:00");
    expect(describeCron("*/5 * * * *")).toContain("Custom");
  });
});

describe("CronBuilder", () => {
  it("emits a cron when a preset part changes", () => {
    const onChange = vi.fn();
    render(<CronBuilder value="0 2 * * *" onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("Frequency"), { target: { value: "hourly" } });
    expect(onChange).toHaveBeenLastCalledWith("0 * * * *");
    fireEvent.change(screen.getByLabelText("Minute"), { target: { value: "30" } });
    expect(onChange).toHaveBeenLastCalledWith("30 * * * *");
  });

  it("exposes a raw cron field in advanced mode", () => {
    const onChange = vi.fn();
    render(<CronBuilder value="0 2 * * *" onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: /advanced/i }));
    fireEvent.change(screen.getByLabelText(/cron expression/i), {
      target: { value: "0 6 * * 1" },
    });
    expect(onChange).toHaveBeenLastCalledWith("0 6 * * 1");
  });
});
