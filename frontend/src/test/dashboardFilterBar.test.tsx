import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { DashboardFilterBar } from "@/components/dashboard/DashboardFilterBar";
import type { NativeFilter } from "@/types/api";

vi.mock("@/api/hooks", async () => {
  const actual = await vi.importActual<typeof import("@/api/hooks")>("@/api/hooks");
  return { ...actual, useSemanticValues: () => ({ data: { values: ["west", "east"] }, isLoading: false }) };
});

const filters: NativeFilter[] = [
  { id: "f1", kind: "value", member: "regional_sales.region", operator: "equals", label: "Region" },
];

function renderBar(props: Partial<React.ComponentProps<typeof DashboardFilterBar>> = {}) {
  const qc = new QueryClient();
  const onSelectionChange = vi.fn();
  const onClearAll = vi.fn();
  const onAddFilter = vi.fn();
  render(
    <QueryClientProvider client={qc}>
      <DashboardFilterBar
        filters={filters}
        selections={{}}
        onSelectionChange={onSelectionChange}
        onClearAll={onClearAll}
        editing={false}
        onAddFilter={onAddFilter}
        onEditFilter={vi.fn()}
        {...props}
      />
    </QueryClientProvider>
  );
  return { onSelectionChange, onClearAll, onAddFilter };
}

describe("DashboardFilterBar", () => {
  it("renders each filter's label in the bar", () => {
    renderBar();
    expect(screen.getByText("Region")).toBeInTheDocument();
  });

  it("calls onClearAll from the Clear all button", () => {
    const { onClearAll } = renderBar();
    fireEvent.click(screen.getByRole("button", { name: /clear all/i }));
    expect(onClearAll).toHaveBeenCalled();
  });

  it("shows Add filter only in edit mode", () => {
    renderBar({ editing: false });
    expect(screen.queryByRole("button", { name: /add filter/i })).not.toBeInTheDocument();
    renderBar({ editing: true });
    expect(screen.getByRole("button", { name: /add filter/i })).toBeInTheDocument();
  });
});
