/**
 * Tests for DashboardFilterBar — the view-time dashboard filter control.
 *
 * useSemanticModels is mocked to supply governed dimensions. Covers: it renders an
 * option per governed dimension, emits an equals filter once a dimension + value are
 * set, and clears back to null.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import type { SemanticModelRead } from "@/types/api";

vi.mock("@/api/hooks", () => ({ useSemanticModels: vi.fn() }));

import { DashboardFilterBar } from "@/components/dashboard/DashboardFilterBar";
import { useSemanticModels } from "@/api/hooks";

const models: SemanticModelRead[] = [
  {
    name: "regional_sales",
    title: "Regional Sales",
    measures: [{ name: "regional_sales.total_amount", title: "Total", type: "number" }],
    dimensions: [{ name: "regional_sales.region", title: "Region", type: "string" }],
  },
];

beforeEach(() => {
  // @ts-expect-error partial mock
  vi.mocked(useSemanticModels).mockReturnValue({ data: models, isLoading: false });
});

afterEach(() => vi.clearAllMocks());

describe("DashboardFilterBar", () => {
  it("renders nothing when there are no governed dimensions", () => {
    // @ts-expect-error partial mock
    vi.mocked(useSemanticModels).mockReturnValue({ data: [], isLoading: false });
    const { container } = render(<DashboardFilterBar value={null} onChange={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("offers each governed dimension and stays null until a value is set", () => {
    const onChange = vi.fn();
    render(<DashboardFilterBar value={null} onChange={onChange} />);

    // The governed dimension is an option.
    expect(screen.getByText(/Regional Sales · Region/)).toBeInTheDocument();

    // Picking a dimension with no value yet → still null (a filter needs a value).
    fireEvent.change(document.querySelector("#dash-filter-dim")!, {
      target: { value: "regional_sales.region" },
    });
    expect(onChange).toHaveBeenLastCalledWith(null);
  });

  it("emits an equals filter when a value is typed for the chosen dimension", () => {
    const onChange = vi.fn();
    // Controlled: the dimension is already chosen (empty value).
    render(
      <DashboardFilterBar
        value={{ member: "regional_sales.region", operator: "equals", values: [] }}
        onChange={onChange}
      />
    );
    fireEvent.change(document.querySelector("#dash-filter-val")!, {
      target: { value: "west" },
    });
    expect(onChange).toHaveBeenLastCalledWith({
      member: "regional_sales.region",
      operator: "equals",
      values: ["west"],
    });
  });

  it("keeps the chosen operator when a value is typed", () => {
    const onChange = vi.fn();
    render(
      <DashboardFilterBar
        value={{ member: "regional_sales.region", operator: "contains", values: [] }}
        onChange={onChange}
      />
    );
    fireEvent.change(document.querySelector("#dash-filter-val")!, { target: { value: "wes" } });
    expect(onChange).toHaveBeenLastCalledWith({
      member: "regional_sales.region",
      operator: "contains",
      values: ["wes"],
    });
  });

  it("emits a valueless filter immediately when a presence operator is picked", () => {
    const onChange = vi.fn();
    render(
      <DashboardFilterBar
        value={{ member: "regional_sales.region", operator: "equals", values: ["west"] }}
        onChange={onChange}
      />
    );
    fireEvent.change(document.querySelector("#dash-filter-op")!, { target: { value: "set" } });
    expect(onChange).toHaveBeenLastCalledWith({
      member: "regional_sales.region",
      operator: "set",
      values: [],
    });
  });

  it("disables the value input for a presence operator", () => {
    render(
      <DashboardFilterBar
        value={{ member: "regional_sales.region", operator: "set", values: [] }}
        onChange={vi.fn()}
      />
    );
    expect(document.querySelector("#dash-filter-val")).toBeDisabled();
  });

  it("offers only dimensions on a cube present in `cubes`", () => {
    // @ts-expect-error partial mock
    vi.mocked(useSemanticModels).mockReturnValue({
      data: [
        ...models,
        {
          name: "orders",
          title: "Orders",
          measures: [{ name: "orders.count", title: "Count", type: "number" }],
          dimensions: [{ name: "orders.status", title: "Status", type: "string" }],
        },
      ],
      isLoading: false,
    });
    // Only the regional_sales cube is on the dashboard → orders.status is hidden.
    render(
      <DashboardFilterBar
        value={null}
        onChange={vi.fn()}
        cubes={new Set(["regional_sales"])}
      />
    );
    expect(screen.getByText(/Regional Sales · Region/)).toBeInTheDocument();
    expect(screen.queryByText(/Orders · Status/)).not.toBeInTheDocument();
  });

  it("splits a comma list into multiple values for set-membership operators", () => {
    const onChange = vi.fn();
    render(
      <DashboardFilterBar
        value={{ member: "regional_sales.region", operator: "equals", values: [] }}
        onChange={onChange}
      />
    );
    fireEvent.change(document.querySelector("#dash-filter-val")!, {
      target: { value: "west, east" },
    });
    expect(onChange).toHaveBeenLastCalledWith({
      member: "regional_sales.region",
      operator: "equals",
      values: ["west", "east"],
    });
  });

  it("keeps a single value for comparison operators", () => {
    const onChange = vi.fn();
    render(
      <DashboardFilterBar
        value={{ member: "regional_sales.region", operator: "gt", values: [] }}
        onChange={onChange}
      />
    );
    fireEvent.change(document.querySelector("#dash-filter-val")!, {
      target: { value: "100, 200" },
    });
    expect(onChange).toHaveBeenLastCalledWith({
      member: "regional_sales.region",
      operator: "gt",
      values: ["100"],
    });
  });

  it("clears the filter", () => {
    const onChange = vi.fn();
    render(
      <DashboardFilterBar
        value={{ member: "regional_sales.region", operator: "equals", values: ["west"] }}
        onChange={onChange}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /clear/i }));
    expect(onChange).toHaveBeenCalledWith(null);
  });
});
