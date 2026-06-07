/**
 * Tests for the Pipelines (ETL) page (#3 UI).
 *
 * All hooks + toast are mocked. Covers empty states, creating a pipeline (posts the
 * full PipelineCreate payload), and run-now triggering the run mutation. Dialogs
 * portal to document.body, so dialog fields are queried by id.
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import type { PipelineRead, SourceConnectionRead } from "@/types/api";

vi.mock("@/api/hooks", () => ({
  useSources: vi.fn(),
  useSourceKinds: vi.fn(),
  useCreateSource: vi.fn(),
  useTestSource: vi.fn(),
  useDeleteSource: vi.fn(),
  usePipelines: vi.fn(),
  usePipelineRuns: vi.fn(),
  useCreatePipeline: vi.fn(),
  useDeletePipeline: vi.fn(),
  useRunPipeline: vi.fn(),
  useSchedules: vi.fn(),
  useCreateSchedule: vi.fn(),
  useDeleteSchedule: vi.fn(),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { Pipelines } from "@/pages/Pipelines";
import * as hooks from "@/api/hooks";

const source: SourceConnectionRead = {
  id: "s1",
  name: "warehouse",
  kind: "sql_database",
  config: {},
  status: "active",
  has_secret: true,
};

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

let createPipelineMutate: ReturnType<typeof vi.fn>;
let runPipelineMutate: ReturnType<typeof vi.fn>;
let createScheduleMutate: ReturnType<typeof vi.fn>;

function query<T>(data: T) {
  return { data, isLoading: false, isError: false };
}
function mutation(spy: ReturnType<typeof vi.fn>) {
  return { mutate: spy, isPending: false };
}

function setup(opts: { sources?: SourceConnectionRead[]; pipelines?: PipelineRead[] }) {
  createPipelineMutate = vi.fn();
  runPipelineMutate = vi.fn();
  createScheduleMutate = vi.fn();
  // @ts-expect-error partial mock
  vi.mocked(hooks.useSources).mockReturnValue(query(opts.sources ?? []));
  // @ts-expect-error partial mock
  vi.mocked(hooks.useSourceKinds).mockReturnValue(query(["sql_database", "filesystem"]));
  // @ts-expect-error partial mock
  vi.mocked(hooks.usePipelines).mockReturnValue(query(opts.pipelines ?? []));
  // @ts-expect-error partial mock
  vi.mocked(hooks.usePipelineRuns).mockReturnValue(query([]));
  // @ts-expect-error partial mock
  vi.mocked(hooks.useCreateSource).mockReturnValue(mutation(vi.fn()));
  // @ts-expect-error partial mock
  vi.mocked(hooks.useTestSource).mockReturnValue(mutation(vi.fn()));
  // @ts-expect-error partial mock
  vi.mocked(hooks.useDeleteSource).mockReturnValue(mutation(vi.fn()));
  // @ts-expect-error partial mock
  vi.mocked(hooks.useCreatePipeline).mockReturnValue(mutation(createPipelineMutate));
  // @ts-expect-error partial mock
  vi.mocked(hooks.useDeletePipeline).mockReturnValue(mutation(vi.fn()));
  // @ts-expect-error partial mock
  vi.mocked(hooks.useRunPipeline).mockReturnValue(mutation(runPipelineMutate));
  // @ts-expect-error partial mock
  vi.mocked(hooks.useSchedules).mockReturnValue(query([]));
  // @ts-expect-error partial mock
  vi.mocked(hooks.useCreateSchedule).mockReturnValue(mutation(createScheduleMutate));
  // @ts-expect-error partial mock
  vi.mocked(hooks.useDeleteSchedule).mockReturnValue(mutation(vi.fn()));
}

afterEach(() => vi.clearAllMocks());

describe("Pipelines page", () => {
  it("shows empty states for sources and pipelines", () => {
    setup({});
    render(<Pipelines />);
    expect(screen.getByText(/no sources yet/i)).toBeInTheDocument();
    expect(screen.getByText(/no pipelines yet/i)).toBeInTheDocument();
  });

  it("creates a pipeline with the full payload", () => {
    setup({ sources: [source] });
    render(<Pipelines />);

    fireEvent.click(screen.getByRole("button", { name: /new pipeline/i }));
    (document.querySelector("#pl-name") as HTMLInputElement).value = "";
    fireEvent.change(document.querySelector("#pl-name")!, { target: { value: "orders_daily" } });
    fireEvent.change(document.querySelector("#pl-object")!, { target: { value: "orders" } });
    fireEvent.change(document.querySelector("#pl-target")!, { target: { value: "orders" } });

    fireEvent.click(screen.getByRole("button", { name: /create pipeline/i }));

    expect(createPipelineMutate).toHaveBeenCalledWith(
      {
        name: "orders_daily",
        source_connection_id: "s1",
        config: { object: "orders", write_disposition: "overwrite" },
        target_table: "orders",
      },
      expect.objectContaining({ onSuccess: expect.any(Function), onError: expect.any(Function) })
    );
  });

  it("runs a pipeline now", () => {
    setup({ sources: [source], pipelines: [pipeline] });
    render(<Pipelines />);
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    expect(runPipelineMutate).toHaveBeenCalledWith(
      "p1",
      expect.objectContaining({ onSuccess: expect.any(Function) })
    );
  });

  it("schedules a pipeline on a cron", () => {
    setup({ sources: [source], pipelines: [pipeline] });
    render(<Pipelines />);
    fireEvent.click(screen.getByRole("button", { name: /schedule/i }));
    fireEvent.change(document.querySelector("#sch-cron")!, { target: { value: "0 6 * * *" } });
    fireEvent.click(screen.getByRole("button", { name: /^add$/i }));
    expect(createScheduleMutate).toHaveBeenCalledWith(
      { name: "orders_daily schedule", target_id: "p1", cron: "0 6 * * *" },
      expect.objectContaining({ onSuccess: expect.any(Function), onError: expect.any(Function) })
    );
  });
});
