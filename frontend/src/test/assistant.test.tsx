/**
 * Tests for the unified Assistant page (#7/#11).
 *
 * The assistant hook + dashboard/chart mutations are mocked, and the chart/data
 * components are stubbed, so the test focuses on the page wiring: a reply renders its
 * answer, tool badges, proposed charts (with save/pin), and insight summaries, and the
 * "Build dashboard" action appears once a chart has been proposed.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import type { AssistantResponse, ChartSpec } from "@/types/api";

vi.mock("@/api/hooks", () => ({
  useAssistant: vi.fn(),
  useCreateChart: vi.fn(() => ({ mutateAsync: vi.fn() })),
  useCreateDashboard: vi.fn(() => ({ mutateAsync: vi.fn() })),
  useAddDashboardTile: vi.fn(() => ({ mutateAsync: vi.fn() })),
}));
vi.mock("@/lib/useChartData", () => ({
  useChartData: vi.fn(() => ({
    data: { columns: ["s.r", "s.t"], rows: [["west", 1]], row_count: 1 },
    isLoading: false,
    isError: false,
  })),
}));
vi.mock("@/components/chart/ChartRenderer", () => ({
  ChartRenderer: () => <div data-testid="chart-renderer" />,
}));
vi.mock("@/components/chart/SaveChartButton", () => ({
  SaveChartButton: () => <button type="button">Save chart</button>,
}));
vi.mock("@/components/dashboard/AddToDashboard", () => ({
  AddToDashboard: () => <button type="button">Add to dashboard</button>,
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { Assistant } from "@/pages/Assistant";
import { useAssistant } from "@/api/hooks";

const spec: ChartSpec = {
  version: "1",
  type: "bar",
  query: { metric_refs: ["sales.total"] },
  encoding: { x: "sales.region", series: [{ field: "sales.total" }] },
  options: { title: "Total by region" },
};

const response: AssistantResponse = {
  answer: "Here is what I found.",
  tools_used: ["nl_to_chart", "summarize_insight"],
  charts: [spec],
  insights: ["Sales grew 12% in the west."],
};

function setup(resp: AssistantResponse) {
  // mutate invokes onSuccess synchronously so the reply renders in-test.
  const mutate = (_req: unknown, opts?: { onSuccess?: (r: AssistantResponse) => void }) =>
    opts?.onSuccess?.(resp);
  vi.mocked(useAssistant).mockReturnValue({
    mutate,
    isPending: false,
    isError: false,
    error: null,
  } as unknown as ReturnType<typeof useAssistant>);
}

afterEach(() => vi.clearAllMocks());
beforeEach(() => setup(response));

function renderAssistant() {
  return render(
    <MemoryRouter>
      <Assistant />
    </MemoryRouter>
  );
}

describe("Assistant page", () => {
  it("renders the reply with answer, tools, charts, and insights", () => {
    renderAssistant();
    // Send via a suggestion chip (empty-state action).
    fireEvent.click(screen.getByRole("button", { name: "What semantic models can I query?" }));

    expect(screen.getByText("Here is what I found.")).toBeInTheDocument();
    expect(screen.getByText("nl_to_chart")).toBeInTheDocument();
    expect(screen.getByText("Sales grew 12% in the west.")).toBeInTheDocument();
    expect(screen.getByTestId("chart-renderer")).toBeInTheDocument();
    // The save action for the proposed chart is present (propose-then-confirm).
    expect(screen.getByRole("button", { name: /save chart/i })).toBeInTheDocument();
  });

  it("offers to build a dashboard once a chart has been proposed", () => {
    renderAssistant();
    expect(screen.queryByRole("button", { name: /build dashboard/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Chart total amount by region." }));
    expect(screen.getByRole("button", { name: /build dashboard \(1\)/i })).toBeInTheDocument();
  });
});
