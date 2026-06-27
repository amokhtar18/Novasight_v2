/**
 * Tests for the Pipelines (ETL) page (#3 UI).
 *
 * All hooks + toast are mocked. Covers empty states, creating a pipeline (posts the
 * full PipelineCreate payload), and run-now triggering the run mutation. Dialogs
 * portal to document.body, so dialog fields are queried by id.
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import type { EngineSpec, PipelineRead, SourceConnectionRead } from "@/types/api";

vi.mock("@/api/hooks", () => ({
  useDatasets: vi.fn(),
  useUploadDataset: vi.fn(),
  useSources: vi.fn(),
  useSourceKinds: vi.fn(),
  useSourceEngines: vi.fn(),
  useIntrospectSource: vi.fn(),
  useCreateSource: vi.fn(),
  useUpdateSource: vi.fn(),
  useTestSource: vi.fn(),
  useDeleteSource: vi.fn(),
  usePipelines: vi.fn(),
  usePipelineRuns: vi.fn(),
  useCreatePipeline: vi.fn(),
  useUpdatePipeline: vi.fn(),
  useDeletePipeline: vi.fn(),
  useRunPipeline: vi.fn(),
  useSchedules: vi.fn(),
  useCreateSchedule: vi.fn(),
  useUpdateSchedule: vi.fn(),
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

const engines: EngineSpec[] = [
  { key: "postgres", label: "PostgreSQL", default_port: 5432, supports_schemas: true, database_label: "Database" },
  { key: "oracle", label: "Oracle", default_port: 1521, supports_schemas: true, database_label: "Service name" },
];

let createPipelineMutate: ReturnType<typeof vi.fn>;
let createSourceMutate: ReturnType<typeof vi.fn>;
let updateSourceMutate: ReturnType<typeof vi.fn>;
let runPipelineMutate: ReturnType<typeof vi.fn>;
let createScheduleMutate: ReturnType<typeof vi.fn>;
let introspectMutateAsync: ReturnType<typeof vi.fn>;

function query<T>(data: T) {
  return { data, isLoading: false, isError: false };
}
function mutation(spy: ReturnType<typeof vi.fn>) {
  return { mutate: spy, isPending: false };
}

function setup(opts: { sources?: SourceConnectionRead[]; pipelines?: PipelineRead[] }) {
  createPipelineMutate = vi.fn();
  createSourceMutate = vi.fn();
  updateSourceMutate = vi.fn();
  runPipelineMutate = vi.fn();
  createScheduleMutate = vi.fn();
  introspectMutateAsync = vi.fn().mockResolvedValue({ schemas: [], tables: [], columns: [] });
  // @ts-expect-error partial mock
  vi.mocked(hooks.useDatasets).mockReturnValue(query([]));
  // @ts-expect-error partial mock
  vi.mocked(hooks.useUploadDataset).mockReturnValue({
    mutate: vi.fn(),
    isPending: false,
    isError: false,
    error: null,
  });
  // @ts-expect-error partial mock
  vi.mocked(hooks.useSources).mockReturnValue(query(opts.sources ?? []));
  // @ts-expect-error partial mock
  vi.mocked(hooks.useSourceKinds).mockReturnValue(query(["sql_database", "filesystem"]));
  // @ts-expect-error partial mock
  vi.mocked(hooks.useSourceEngines).mockReturnValue(query(engines));
  vi.mocked(hooks.useIntrospectSource).mockReturnValue({
    mutateAsync: introspectMutateAsync,
    isPending: false,
  } as unknown as ReturnType<typeof hooks.useIntrospectSource>);
  // @ts-expect-error partial mock
  vi.mocked(hooks.usePipelines).mockReturnValue(query(opts.pipelines ?? []));
  // @ts-expect-error partial mock
  vi.mocked(hooks.usePipelineRuns).mockReturnValue(query([]));
  // @ts-expect-error partial mock
  vi.mocked(hooks.useCreateSource).mockReturnValue(mutation(createSourceMutate));
  // @ts-expect-error partial mock
  vi.mocked(hooks.useUpdateSource).mockReturnValue(mutation(updateSourceMutate));
  // @ts-expect-error partial mock
  vi.mocked(hooks.useUpdatePipeline).mockReturnValue(mutation(vi.fn()));
  // @ts-expect-error partial mock
  vi.mocked(hooks.useUpdateSchedule).mockReturnValue(mutation(vi.fn()));
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

// The page is the tabbed Ingest hub (#1): "Data sources" is the default tab; the
// pipeline + schedule flows live behind the "Pipelines" tab. The hub uses router
// hooks, so renders are wrapped in a MemoryRouter.
function renderHub() {
  return render(
    <MemoryRouter>
      <Pipelines />
    </MemoryRouter>
  );
}
function goToPipelinesTab() {
  fireEvent.click(screen.getByRole("tab", { name: "Pipelines" }));
}

describe("Pipelines page", () => {
  it("shows empty states for sources and pipelines", () => {
    setup({});
    renderHub();
    expect(screen.getByText(/no sources yet/i)).toBeInTheDocument();
    goToPipelinesTab();
    expect(screen.getByText(/no pipelines yet/i)).toBeInTheDocument();
  });

  it("creates a source with the selected engine and its default port", () => {
    setup({});
    renderHub();

    fireEvent.click(screen.getByRole("button", { name: /new source/i }));
    fireEvent.change(document.querySelector("#src-name")!, { target: { value: "wh" } });
    // Switching engine prefills the engine's standard port (1521 for Oracle).
    fireEvent.change(document.querySelector("#src-engine")!, { target: { value: "oracle" } });
    fireEvent.change(document.querySelector("#src-host")!, { target: { value: "db" } });
    fireEvent.change(document.querySelector("#src-database")!, { target: { value: "orcl" } });

    fireEvent.click(screen.getByRole("button", { name: /create source/i }));

    expect(createSourceMutate).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "wh",
        kind: "sql_database",
        config: expect.objectContaining({
          engine: "oracle",
          database: "orcl",
          host: "db",
          port: 1521,
        }),
      }),
      expect.objectContaining({ onSuccess: expect.any(Function), onError: expect.any(Function) })
    );
  });

  it("edits a source, keeping the secret when the password is left blank", () => {
    const dbSource: SourceConnectionRead = {
      id: "s9",
      name: "warehouse",
      kind: "sql_database",
      config: { engine: "postgres", host: "db", port: 5432, database: "sales", username: "ro" },
      status: "active",
      has_secret: true,
    };
    setup({ sources: [dbSource] });
    renderHub();

    fireEvent.click(screen.getByRole("button", { name: /edit warehouse/i }));
    fireEvent.change(document.querySelector("#src-database")!, { target: { value: "analytics" } });
    fireEvent.click(screen.getByRole("button", { name: /save source/i }));

    expect(updateSourceMutate).toHaveBeenCalledWith(
      {
        id: "s9",
        patch: expect.objectContaining({
          name: "warehouse",
          config: expect.objectContaining({ engine: "postgres", database: "analytics" }),
        }),
      },
      expect.objectContaining({ onSuccess: expect.any(Function), onError: expect.any(Function) })
    );
    // No secret sent when the password field was left blank.
    expect(updateSourceMutate.mock.calls[0][0].patch.secret).toBeUndefined();
  });

  it("creates a pipeline from a file source (Details → Review)", () => {
    const fileSource: SourceConnectionRead = { ...source, id: "f1", name: "lake", kind: "filesystem" };
    setup({ sources: [fileSource] });
    renderHub();
    goToPipelinesTab();

    fireEvent.click(screen.getByRole("button", { name: /new pipeline/i }));
    fireEvent.change(document.querySelector("#pl-name")!, { target: { value: "orders_daily" } });
    fireEvent.change(document.querySelector("#pl-object")!, { target: { value: "raw/orders.csv" } });
    fireEvent.change(document.querySelector("#pl-target")!, { target: { value: "orders" } });
    fireEvent.click(screen.getByRole("button", { name: /^next$/i })); // → Review
    fireEvent.click(screen.getByRole("button", { name: /create pipeline/i }));

    expect(createPipelineMutate).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "orders_daily",
        source_connection_id: "f1",
        target_table: "orders",
        config: expect.objectContaining({
          object: "raw/orders.csv",
          write_disposition: "overwrite",
        }),
      }),
      expect.objectContaining({ onSuccess: expect.any(Function), onError: expect.any(Function) })
    );
  });

  it("designs a SQL pipeline with a field map and merge-by-primary-key", async () => {
    setup({ sources: [source] }); // sql_database
    // Configure the drill-down after setup() has (re)created the spy.
    introspectMutateAsync.mockImplementation(
      async (vars: { schema?: string; table?: string }) => {
        if (vars.table)
          return {
            schemas: [],
            tables: [],
            columns: [
              { name: "id", source_type: "INTEGER", suggested_target_type: "Int64" },
              { name: "region", source_type: "TEXT", suggested_target_type: "String" },
            ],
          };
        if (vars.schema) return { schemas: [], tables: ["orders"], columns: [] };
        return { schemas: ["public"], tables: [], columns: [] };
      }
    );
    renderHub();
    goToPipelinesTab();

    fireEvent.click(screen.getByRole("button", { name: /new pipeline/i }));
    fireEvent.change(document.querySelector("#pl-name")!, { target: { value: "orders_sync" } });
    fireEvent.change(document.querySelector("#pl-target")!, { target: { value: "orders" } });
    fireEvent.click(screen.getByRole("button", { name: /^next$/i })); // → Schema & table (loads schemas)

    // Wait for each async-loaded option before selecting it.
    await screen.findByRole("option", { name: "public" });
    fireEvent.change(screen.getByRole("combobox", { name: /schema/i }), {
      target: { value: "public" },
    });
    await screen.findByRole("option", { name: "orders" });
    fireEvent.change(screen.getByRole("combobox", { name: /^table$/i }), {
      target: { value: "orders" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^next$/i })); // → Fields (loads columns)

    // Both columns introspected and included by default.
    await screen.findByLabelText("Include id");
    expect(screen.getByLabelText("Include id")).toHaveClass("accent-primary");
    fireEvent.click(screen.getByRole("button", { name: /^next$/i })); // → Load mode

    fireEvent.change(screen.getByLabelText(/load mode/i), { target: { value: "merge" } });
    fireEvent.click(screen.getByLabelText("Primary key id"));
    fireEvent.click(screen.getByRole("button", { name: /^next$/i })); // → Review
    fireEvent.click(screen.getByRole("button", { name: /create pipeline/i }));

    expect(createPipelineMutate).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "orders_sync",
        source_connection_id: "s1",
        target_table: "orders",
        config: expect.objectContaining({
          object: "orders",
          source_schema: "public",
          write_disposition: "merge",
          primary_key: ["id"],
        }),
      }),
      expect.objectContaining({ onSuccess: expect.any(Function), onError: expect.any(Function) })
    );
    const cfg = createPipelineMutate.mock.calls[0][0].config;
    expect(cfg.columns).toHaveLength(2);
  });

  it("runs a pipeline now", () => {
    setup({ sources: [source], pipelines: [pipeline] });
    renderHub();
    goToPipelinesTab();
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    expect(runPipelineMutate).toHaveBeenCalledWith(
      "p1",
      expect.objectContaining({ onSuccess: expect.any(Function) })
    );
  });

  it("schedules a pipeline via the cron builder (advanced mode)", () => {
    setup({ sources: [source], pipelines: [pipeline] });
    renderHub();
    goToPipelinesTab();
    fireEvent.click(screen.getByRole("button", { name: /schedule/i }));
    // The raw cron input lives under the builder's Advanced tab.
    fireEvent.click(screen.getByRole("button", { name: /advanced/i }));
    fireEvent.change(document.querySelector("#sch-cron")!, { target: { value: "0 6 * * *" } });
    fireEvent.click(screen.getByRole("button", { name: /add schedule/i }));
    expect(createScheduleMutate).toHaveBeenCalledWith(
      { name: "orders_daily schedule", pipeline_ids: ["p1"], cron: "0 6 * * *" },
      expect.objectContaining({ onSuccess: expect.any(Function), onError: expect.any(Function) })
    );
  });
});
