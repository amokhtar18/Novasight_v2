/**
 * Tests for the DbtModels (Transforms) wizard (#5/#6).
 *
 * Hooks + toast mocked. Covers the empty state and the create flow: filling name,
 * SQL, and a column test posts the full DbtModelDefCreate payload (accepted_values
 * splits its comma list). Dialog fields are queried by id (portal to body).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

vi.mock("@/api/hooks", () => ({
  useDbtModels: vi.fn(),
  useCreateDbtModel: vi.fn(),
  useUpdateDbtModel: vi.fn(),
  useDeleteDbtModel: vi.fn(),
  useRunDbtModel: vi.fn(),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { DbtModels } from "@/pages/DbtModels";
import {
  useCreateDbtModel,
  useDeleteDbtModel,
  useDbtModels,
  useRunDbtModel,
  useUpdateDbtModel,
} from "@/api/hooks";
import type { DbtModelDefRead } from "@/types/api";

const mockModels = vi.mocked(useDbtModels);
const mockCreate = vi.mocked(useCreateDbtModel);
const mockUpdate = vi.mocked(useUpdateDbtModel);
const mockDelete = vi.mocked(useDeleteDbtModel);
const mockRun = vi.mocked(useRunDbtModel);

let createMutateAsync: ReturnType<typeof vi.fn>;
let updateMutateAsync: ReturnType<typeof vi.fn>;
let runMutate: ReturnType<typeof vi.fn>;

beforeEach(() => {
  createMutateAsync = vi.fn().mockResolvedValue({ id: "m1", name: "mart_orders" });
  updateMutateAsync = vi.fn().mockResolvedValue({ id: "m1", name: "mart_orders" });
  runMutate = vi.fn();
  // @ts-expect-error partial mock
  mockModels.mockReturnValue({ data: [], isLoading: false });
  // @ts-expect-error partial mock
  mockCreate.mockReturnValue({ mutateAsync: createMutateAsync, isPending: false });
  // @ts-expect-error partial mock
  mockUpdate.mockReturnValue({ mutateAsync: updateMutateAsync, isPending: false });
  // @ts-expect-error partial mock
  mockDelete.mockReturnValue({ mutate: vi.fn() });
  // @ts-expect-error partial mock
  mockRun.mockReturnValue({ mutate: runMutate, isPending: false, variables: undefined });
});

afterEach(() => vi.clearAllMocks());

function setValue(id: string, value: string) {
  fireEvent.change(document.querySelector(`#${id}`)!, { target: { value } });
}

const existingModel: DbtModelDefRead = {
  id: "m1",
  name: "mart_orders",
  layer: "marts",
  materialization: "table",
  sql: "select 1",
  config: {},
  incremental: null,
  enabled: true,
  tests: [],
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-06-01T00:00:00Z",
};

describe("DbtModels wizard", () => {
  it("shows the empty state with no models", () => {
    render(<DbtModels />);
    expect(screen.getByText(/no dbt models yet/i)).toBeInTheDocument();
  });

  it("edits an existing model, posting the patch", async () => {
    // @ts-expect-error partial mock
    mockModels.mockReturnValue({ data: [existingModel], isLoading: false });
    render(<DbtModels />);

    fireEvent.click(screen.getByRole("button", { name: /edit mart_orders/i }));
    setValue("dm-sql", "select 2");
    fireEvent.click(screen.getByRole("button", { name: /save model/i }));

    await waitFor(() => expect(updateMutateAsync).toHaveBeenCalled());
    expect(updateMutateAsync).toHaveBeenCalledWith({
      id: "m1",
      patch: expect.objectContaining({ name: "mart_orders", sql: "select 2" }),
    });
  });

  it("posts the full model definition with a column test", async () => {
    render(<DbtModels />);
    fireEvent.click(screen.getAllByRole("button", { name: /new model/i })[0]);

    setValue("dm-name", "mart_orders");
    setValue("dm-sql", "select region from {{ ref('stg') }}");
    setValue("t-col-0", "region");
    setValue("t-type-0", "accepted_values");
    setValue("t-vals-0", "west, east");

    fireEvent.click(screen.getByRole("button", { name: /create model/i }));

    await waitFor(() => expect(createMutateAsync).toHaveBeenCalled());
    expect(createMutateAsync).toHaveBeenCalledWith({
      name: "mart_orders",
      layer: "marts",
      materialization: "table",
      sql: "select region from {{ ref('stg') }}",
      tests: [
        { column_name: "region", test_type: "accepted_values", config: { values: ["west", "east"] } },
      ],
    });
  });

  it("posts a relationships test with its to/field config", async () => {
    render(<DbtModels />);
    fireEvent.click(screen.getAllByRole("button", { name: /new model/i })[0]);

    setValue("dm-name", "mart_orders");
    setValue("dm-sql", "select customer_id from {{ ref('stg') }}");
    setValue("t-col-0", "customer_id");
    setValue("t-type-0", "relationships");
    // The to/field inputs appear once the type flips to relationships.
    setValue("t-to-0", "ref('stg_customers')");
    setValue("t-field-0", "id");

    fireEvent.click(screen.getByRole("button", { name: /create model/i }));

    await waitFor(() => expect(createMutateAsync).toHaveBeenCalled());
    expect(createMutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        tests: [
          {
            column_name: "customer_id",
            test_type: "relationships",
            config: { to: "ref('stg_customers')", field: "id" },
          },
        ],
      })
    );
  });

  it("runs a model when its Run button is clicked", () => {
    const model = {
      id: "m1", name: "mart_orders", layer: "marts", materialization: "table",
      sql: "select 1", config: {}, enabled: true, tests: [],
      created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
    };
    // @ts-expect-error partial mock
    mockModels.mockReturnValue({ data: [model], isLoading: false });
    render(<DbtModels />);
    fireEvent.click(screen.getByRole("button", { name: /run mart_orders/i }));
    expect(runMutate).toHaveBeenCalledWith("m1", expect.any(Object));
  });

  it("includes incremental settings when materialization is incremental", async () => {
    render(<DbtModels />);
    fireEvent.click(screen.getAllByRole("button", { name: /new model/i })[0]);

    setValue("dm-name", "mart_events");
    setValue("dm-sql", "select * from {{ ref('stg') }}");
    setValue("dm-mat", "incremental");
    // Incremental fields appear only once the materialization flips.
    setValue("dm-unique-key", "event_id, ts");
    setValue("dm-strategy", "merge");
    setValue("dm-schema-change", "append_new_columns");

    fireEvent.click(screen.getByRole("button", { name: /create model/i }));

    await waitFor(() => expect(createMutateAsync).toHaveBeenCalled());
    expect(createMutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        materialization: "incremental",
        incremental: {
          unique_key: ["event_id", "ts"],
          incremental_strategy: "merge",
          on_schema_change: "append_new_columns",
        },
      })
    );
  });
});
