// frontend/src/test/dashboardFilterDrawer.test.tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { DashboardFilterDrawer } from "@/components/dashboard/DashboardFilterDrawer";
import type { NativeFilter } from "@/types/api";

vi.mock("@/api/hooks", () => ({
  useSemanticValues: () => ({ data: { values: ["west", "east"] }, isLoading: false }),
}));

const filters: NativeFilter[] = [
  { id: "f1", kind: "value", member: "regional_sales.region", operator: "equals", label: "Region" },
];

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient();
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe("DashboardFilterDrawer", () => {
  it("renders a control per filter and a Clear all", () => {
    wrap(
      <DashboardFilterDrawer
        filters={filters}
        selections={{}}
        onSelectionChange={() => {}}
        onClearAll={() => {}}
        editing={false}
      />
    );
    expect(screen.getByText("Region")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /clear all/i })).toBeInTheDocument();
  });

  it("Clear all fires the callback", () => {
    const onClearAll = vi.fn();
    wrap(
      <DashboardFilterDrawer filters={filters} selections={{}} onSelectionChange={() => {}} onClearAll={onClearAll} editing={false} />
    );
    fireEvent.click(screen.getByRole("button", { name: /clear all/i }));
    expect(onClearAll).toHaveBeenCalled();
  });

  it("shows Add filter only in edit mode", () => {
    const { rerender } = wrap(
      <DashboardFilterDrawer filters={filters} selections={{}} onSelectionChange={() => {}} onClearAll={() => {}} editing={false} onAddFilter={() => {}} />
    );
    expect(screen.queryByRole("button", { name: /add filter/i })).not.toBeInTheDocument();
    const qc = new QueryClient();
    rerender(
      <QueryClientProvider client={qc}>
        <DashboardFilterDrawer filters={filters} selections={{}} onSelectionChange={() => {}} onClearAll={() => {}} editing onAddFilter={() => {}} />
      </QueryClientProvider>
    );
    expect(screen.getByRole("button", { name: /add filter/i })).toBeInTheDocument();
  });
});
