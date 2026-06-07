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
  useDeleteSemanticModelDef: vi.fn(),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { SemanticModels } from "@/pages/SemanticModels";
import {
  useCreateSemanticModelDef,
  useDeleteSemanticModelDef,
  useSemanticModelDefs,
} from "@/api/hooks";

const mockDefs = vi.mocked(useSemanticModelDefs);
const mockCreate = vi.mocked(useCreateSemanticModelDef);
const mockDelete = vi.mocked(useDeleteSemanticModelDef);

let createMutateAsync: ReturnType<typeof vi.fn>;

beforeEach(() => {
  createMutateAsync = vi.fn().mockResolvedValue({ id: "m1", name: "sales" });
  // @ts-expect-error partial mock
  mockDefs.mockReturnValue({ data: [], isLoading: false });
  // @ts-expect-error partial mock
  mockCreate.mockReturnValue({ mutateAsync: createMutateAsync, isPending: false });
  // @ts-expect-error partial mock
  mockDelete.mockReturnValue({ mutate: vi.fn() });
});

afterEach(() => vi.clearAllMocks());

function setValue(id: string, value: string) {
  const el = document.querySelector(`#${id}`) as HTMLInputElement;
  fireEvent.change(el, { target: { value } });
}

describe("SemanticModels", () => {
  it("shows the empty state when there are no models", () => {
    render(<SemanticModels />);
    expect(screen.getByText(/no semantic models yet/i)).toBeInTheDocument();
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
