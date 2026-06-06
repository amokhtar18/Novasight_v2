/**
 * Tests for SaveChartButton — server-side chart persistence (#9).
 *
 * The create-chart hook and toast are mocked (no network). Covers: the dialog
 * seeds its name from the suggested title, and Save posts the full ChartCreate
 * payload (name + spec + source_kind + source_ref) then reports success.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import type { ChartSpec } from "@/types/api";

vi.mock("@/api/hooks", () => ({ useCreateChart: vi.fn() }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { SaveChartButton } from "@/components/chart/SaveChartButton";
import { useCreateChart } from "@/api/hooks";
import { toast } from "sonner";

const mockUseCreateChart = vi.mocked(useCreateChart);

const spec: ChartSpec = {
  version: "1",
  type: "bar",
  query: { metric_refs: ["regional_sales.total_amount"] },
  encoding: {
    x: "regional_sales.region",
    series: [{ field: "regional_sales.total_amount", name: "Total" }],
  },
  options: { title: "Total by region" },
};

function makeMutationReturn(overrides: {
  isPending?: boolean;
  mutate?: (...args: unknown[]) => void;
}) {
  return {
    isPending: overrides.isPending ?? false,
    mutate: overrides.mutate ?? vi.fn(),
    error: null,
    data: undefined,
    isError: false,
    isSuccess: false,
    isIdle: true,
    reset: vi.fn(),
    mutateAsync: vi.fn(),
    status: "idle" as const,
    variables: undefined,
    context: undefined,
    failureCount: 0,
    failureReason: null,
    submittedAt: 0,
  };
}

beforeEach(() => {
  // @ts-expect-error partial mock
  mockUseCreateChart.mockReturnValue(makeMutationReturn({}));
});

afterEach(() => vi.clearAllMocks());

describe("SaveChartButton", () => {
  it("opens a dialog seeded with the suggested name", () => {
    render(<SaveChartButton spec={spec} defaultName="Total by region" />);
    fireEvent.click(screen.getByRole("button", { name: /save chart/i }));

    const input = screen.getByLabelText(/chart name/i) as HTMLInputElement;
    expect(input.value).toBe("Total by region");
  });

  it("posts the full ChartCreate payload and reports success", () => {
    const mutateSpy = vi.fn(
      (_vars: unknown, cbs?: { onSuccess?: (c: { name: string }) => void }) => {
        cbs?.onSuccess?.({ name: "Region totals" });
      }
    );
    // @ts-expect-error partial mock
    mockUseCreateChart.mockReturnValue(makeMutationReturn({ mutate: mutateSpy }));

    render(
      <SaveChartButton
        spec={spec}
        defaultName="Total by region"
        sourceKind="semantic"
        sourceRef="regional_sales"
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /save chart/i }));
    fireEvent.change(screen.getByLabelText(/chart name/i), {
      target: { value: "Region totals" },
    });
    // The footer "Save" button (distinct from the "Save chart" trigger).
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

    expect(mutateSpy).toHaveBeenCalledWith(
      {
        name: "Region totals",
        spec,
        source_kind: "semantic",
        source_ref: "regional_sales",
      },
      expect.objectContaining({ onSuccess: expect.any(Function), onError: expect.any(Function) })
    );
    expect(toast.success).toHaveBeenCalledWith('Saved “Region totals”');
  });

  it("does not submit a blank name", () => {
    const mutateSpy = vi.fn();
    // @ts-expect-error partial mock
    mockUseCreateChart.mockReturnValue(makeMutationReturn({ mutate: mutateSpy }));

    render(<SaveChartButton spec={spec} defaultName="" />);
    fireEvent.click(screen.getByRole("button", { name: /save chart/i }));

    // Save is disabled while the name is empty.
    expect(screen.getByRole("button", { name: /^save$/i })).toBeDisabled();
    expect(mutateSpy).not.toHaveBeenCalled();
  });
});
