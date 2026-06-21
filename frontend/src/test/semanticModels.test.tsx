/**
 * Tests for the SemanticModels wizard (#8).
 *
 * Hooks + toast are mocked. Covers the empty state and the create flow: filling the
 * name, base table, a measure, and a dimension posts the full SemanticModelDefCreate
 * payload. (The dialog portals to document.body, so row fields are queried by id.)
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

vi.mock("@/api/hooks", () => ({
  useSemanticModelDefs: vi.fn(),
  useCreateSemanticModelDef: vi.fn(),
  useUpdateSemanticModelDef: vi.fn(),
  useDeleteSemanticModelDef: vi.fn(),
  useServingTables: vi.fn(),
  useServingColumns: vi.fn(),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { SemanticModels } from "@/pages/SemanticModels";
import {
  useCreateSemanticModelDef,
  useDeleteSemanticModelDef,
  useSemanticModelDefs,
  useServingColumns,
  useServingTables,
  useUpdateSemanticModelDef,
} from "@/api/hooks";
import type { SemanticModelDefRead } from "@/types/api";

const mockDefs = vi.mocked(useSemanticModelDefs);
const mockCreate = vi.mocked(useCreateSemanticModelDef);
const mockUpdate = vi.mocked(useUpdateSemanticModelDef);
const mockDelete = vi.mocked(useDeleteSemanticModelDef);

let createMutateAsync: ReturnType<typeof vi.fn>;
let updateMutateAsync: ReturnType<typeof vi.fn>;

beforeEach(() => {
  createMutateAsync = vi.fn().mockResolvedValue({ id: "m1", name: "sales" });
  updateMutateAsync = vi.fn().mockResolvedValue({ id: "m1", name: "sales" });
  // @ts-expect-error partial mock
  mockDefs.mockReturnValue({ data: [], isLoading: false });
  // @ts-expect-error partial mock
  mockCreate.mockReturnValue({ mutateAsync: createMutateAsync, isPending: false });
  // @ts-expect-error partial mock
  mockUpdate.mockReturnValue({ mutateAsync: updateMutateAsync, isPending: false });
  // @ts-expect-error partial mock
  mockDelete.mockReturnValue({ mutate: vi.fn() });
  // @ts-expect-error partial mock
  vi.mocked(useServingTables).mockReturnValue({ data: [] });
  // @ts-expect-error partial mock
  vi.mocked(useServingColumns).mockReturnValue({ data: [] });
});

afterEach(() => vi.clearAllMocks());

function setValue(id: string, value: string) {
  const el = document.querySelector(`#${id}`) as HTMLInputElement;
  fireEvent.change(el, { target: { value } });
}

const existingDef: SemanticModelDefRead = {
  id: "m1",
  name: "sales",
  base_table: "mart_sales",
  config: {
    measures: [{ name: "revenue", type: "sum", sql: "amount" }],
    dimensions: [{ name: "region", type: "string", sql: "region" }],
  },
  enabled: true,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-06-01T00:00:00Z",
};

describe("SemanticModels", () => {
  it("shows the empty state when there are no models", () => {
    render(<SemanticModels />);
    expect(screen.getByText(/no semantic models yet/i)).toBeInTheDocument();
  });

  it("edits an existing model, posting the patch", async () => {
    // @ts-expect-error partial mock
    mockDefs.mockReturnValue({ data: [existingDef], isLoading: false });
    render(<SemanticModels />);

    fireEvent.click(screen.getByRole("button", { name: /edit sales/i }));
    setValue("sm-table", "mart_sales_v2");
    fireEvent.click(screen.getByRole("button", { name: /save model/i }));

    await waitFor(() => expect(updateMutateAsync).toHaveBeenCalled());
    expect(updateMutateAsync).toHaveBeenCalledWith({
      id: "m1",
      patch: expect.objectContaining({ name: "sales", base_table: "mart_sales_v2" }),
    });
  });

  it("posts the full definition from the wizard", async () => {
    render(<SemanticModels />);
    // Empty state + header both expose "New model"; either opens the wizard.
    fireEvent.click(screen.getAllByRole("button", { name: /new model/i })[0]);

    setValue("sm-name", "sales");
    setValue("sm-table", "mart_sales");
    setValue("m-name-0", "total_amount");
    setValue("m-sql-0", "amount");
    setValue("d-name-0", "region");
    setValue("d-sql-0", "region");

    fireEvent.click(screen.getByRole("button", { name: /create model/i }));

    await waitFor(() => expect(createMutateAsync).toHaveBeenCalled());
    expect(createMutateAsync).toHaveBeenCalledWith({
      name: "sales",
      base_table: "mart_sales",
      config: {
        measures: [{ name: "total_amount", type: "sum", sql: "amount" }],
        dimensions: [{ name: "region", type: "string", sql: "region" }],
      },
    });
  });

  it("includes a join when a join row is filled", async () => {
    render(<SemanticModels />);
    fireEvent.click(screen.getAllByRole("button", { name: /new model/i })[0]);

    setValue("sm-name", "orders");
    setValue("sm-table", "mart_orders");
    setValue("m-name-0", "rows");
    setValue("m-type-0", "count");

    // Joins start collapsed; the Joins section's "Add" is the last Add button.
    const addButtons = screen.getAllByRole("button", { name: /^add$/i });
    fireEvent.click(addButtons[addButtons.length - 1]);
    setValue("j-name-0", "customers");
    setValue("j-local-0", "customer_id");
    setValue("j-foreign-0", "id");

    fireEvent.click(screen.getByRole("button", { name: /create model/i }));

    await waitFor(() => expect(createMutateAsync).toHaveBeenCalled());
    expect(createMutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        config: expect.objectContaining({
          joins: [
            {
              name: "customers",
              relationship: "many_to_one",
              local_key: "customer_id",
              foreign_key: "id",
            },
          ],
        }),
      })
    );
  });

  it("sends composite keys for a multi-column join (#6)", async () => {
    render(<SemanticModels />);
    fireEvent.click(screen.getAllByRole("button", { name: /new model/i })[0]);

    setValue("sm-name", "orders");
    setValue("sm-table", "mart_orders");
    setValue("m-name-0", "rows");
    setValue("m-type-0", "count");

    const addButtons = screen.getAllByRole("button", { name: /^add$/i });
    fireEvent.click(addButtons[addButtons.length - 1]);
    setValue("j-name-0", "line_items");
    setValue("j-local-0", "order_id, region");
    setValue("j-foreign-0", "order_id, region");

    fireEvent.click(screen.getByRole("button", { name: /create model/i }));

    await waitFor(() => expect(createMutateAsync).toHaveBeenCalled());
    expect(createMutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        config: expect.objectContaining({
          joins: [
            {
              name: "line_items",
              relationship: "many_to_one",
              local_keys: ["order_id", "region"],
              foreign_keys: ["order_id", "region"],
            },
          ],
        }),
      })
    );
  });

  it("lists existing models with member counts", () => {
    // @ts-expect-error partial mock
    mockDefs.mockReturnValue({
      data: [
        {
          id: "m1",
          name: "sales",
          base_table: "mart_sales",
          enabled: true,
          config: {
            measures: [{ name: "total_amount", type: "sum", sql: "amount" }],
            dimensions: [{ name: "region", type: "string", sql: "region" }],
          },
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        },
      ],
      isLoading: false,
    });
    render(<SemanticModels />);
    expect(screen.getByText("sales")).toBeInTheDocument();
    expect(screen.getByText(/over mart_sales/i)).toBeInTheDocument();
    expect(screen.getByText(/1 measure/i)).toBeInTheDocument();
  });
});
