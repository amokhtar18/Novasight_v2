/**
 * Tests for the Operations page (Phase 2 — operations UIs).
 *
 * All hooks, identity, and toast are mocked. Covers empty states, the recent-runs
 * feed (pipeline name + status), pause/resume calling useUpdateSchedule with the
 * flipped `enabled`, and superuser gating hiding the manage controls.
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import type { PipelineRead, PipelineRunSummary, ScheduleRead } from "@/types/api";

vi.mock("@/api/hooks", () => ({
  useSchedules: vi.fn(),
  usePipelines: vi.fn(),
  useRecentRuns: vi.fn(),
  useCreateSchedule: vi.fn(),
  useUpdateSchedule: vi.fn(),
  useDeleteSchedule: vi.fn(),
}));
vi.mock("@/lib/identity", () => ({ useIdentity: vi.fn() }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { Operations } from "@/pages/Operations";
import * as hooks from "@/api/hooks";
import { useIdentity } from "@/lib/identity";

const pipeline: PipelineRead = {
  id: "p1",
  name: "orders_daily",
  source_connection_id: "s1",
  config: { object: "orders", write_disposition: "overwrite" },
  target_table: "orders",
  enabled: true,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const schedule: ScheduleRead = {
  id: "sch1",
  name: "nightly",
  target_kind: "pipeline",
  pipeline_ids: ["p1"],
  cron: "0 2 * * *",
  enabled: true,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const run: PipelineRunSummary = {
  id: "r1",
  pipeline_id: "p1",
  pipeline_name: "orders_daily",
  status: "success",
  dagster_run_id: null,
  rows: 42,
  started_at: "2026-01-01T00:00:00Z",
  finished_at: "2026-01-01T00:01:00Z",
  error: null,
  created_at: "2026-01-01T00:00:00Z",
};

let updateScheduleMutate: ReturnType<typeof vi.fn>;

function query<T>(data: T) {
  return { data, isLoading: false, isError: false };
}
function mutation(spy: ReturnType<typeof vi.fn>) {
  return { mutate: spy, isPending: false };
}

function setup(opts: {
  schedules?: ScheduleRead[];
  pipelines?: PipelineRead[];
  runs?: PipelineRunSummary[];
  isSuperuser?: boolean;
}) {
  updateScheduleMutate = vi.fn();
  // @ts-expect-error partial mock
  vi.mocked(hooks.useSchedules).mockReturnValue(query(opts.schedules ?? []));
  // @ts-expect-error partial mock
  vi.mocked(hooks.usePipelines).mockReturnValue(query(opts.pipelines ?? []));
  // @ts-expect-error partial mock
  vi.mocked(hooks.useRecentRuns).mockReturnValue(query(opts.runs ?? []));
  // @ts-expect-error partial mock
  vi.mocked(hooks.useCreateSchedule).mockReturnValue(mutation(vi.fn()));
  // @ts-expect-error partial mock
  vi.mocked(hooks.useUpdateSchedule).mockReturnValue(mutation(updateScheduleMutate));
  // @ts-expect-error partial mock
  vi.mocked(hooks.useDeleteSchedule).mockReturnValue(mutation(vi.fn()));
  // @ts-expect-error partial mock
  vi.mocked(useIdentity).mockReturnValue({ isSuperuser: opts.isSuperuser ?? true });
}

afterEach(() => vi.clearAllMocks());

describe("Operations page", () => {
  it("shows empty states for schedules and runs", () => {
    setup({});
    render(<Operations />);
    expect(screen.getByText(/no schedules yet/i)).toBeInTheDocument();
    expect(screen.getByText(/no runs yet/i)).toBeInTheDocument();
  });

  it("renders a schedule with its pipeline name and a run in the feed", () => {
    setup({ schedules: [schedule], pipelines: [pipeline], runs: [run] });
    render(<Operations />);
    expect(screen.getByText("nightly")).toBeInTheDocument();
    // cron + pipeline name in the schedule row, pipeline name in the run row.
    expect(screen.getByText(/0 2 \* \* \*/)).toBeInTheDocument();
    expect(screen.getAllByText("orders_daily").length).toBeGreaterThan(0);
    expect(screen.getByText("success")).toBeInTheDocument();
    expect(screen.getByText(/42 rows/)).toBeInTheDocument();
  });

  it("pauses an enabled schedule by flipping enabled", () => {
    setup({ schedules: [schedule], pipelines: [pipeline] });
    render(<Operations />);
    fireEvent.click(screen.getByRole("button", { name: /pause/i }));
    expect(updateScheduleMutate).toHaveBeenCalledWith(
      { id: "sch1", patch: { enabled: false } },
      expect.objectContaining({ onSuccess: expect.any(Function), onError: expect.any(Function) })
    );
  });

  it("hides manage controls for non-superusers", () => {
    setup({ schedules: [schedule], pipelines: [pipeline], isSuperuser: false });
    render(<Operations />);
    expect(screen.queryByRole("button", { name: /pause/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /delete schedule/i })).not.toBeInTheDocument();
  });

  it("filters the recent-runs feed by status (#2)", () => {
    const ok: PipelineRunSummary = { ...run, id: "r1", pipeline_name: "orders_daily", pipeline_id: "p1", status: "success" };
    const bad: PipelineRunSummary = {
      ...run, id: "r2", pipeline_name: "customers", pipeline_id: "p2",
      status: "error", rows: null, error: "boom",
    };
    setup({ runs: [ok, bad] });
    render(<Operations />);
    // Both run rows show with the default "All statuses" filter (assert on row-unique
    // content — the pipeline names also appear as <option>s in the filter dropdown).
    expect(screen.getByText(/42 rows/)).toBeInTheDocument();
    expect(screen.getByText("boom")).toBeInTheDocument();
    // Narrowing to errors drops the successful run's row.
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "error" } });
    expect(screen.queryByText(/42 rows/)).not.toBeInTheDocument();
    expect(screen.getByText("boom")).toBeInTheDocument();
  });

  it("shows a run duration in the feed (#2)", () => {
    setup({ runs: [run] }); // started 00:00:00 → finished 00:01:00
    render(<Operations />);
    expect(screen.getByText(/1m 0s/)).toBeInTheDocument();
  });
});
