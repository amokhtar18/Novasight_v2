/**
 * Vitest + React Testing Library tests for NLChartPanel (Task 4.4).
 *
 * The API hook is mocked — no network calls are made. Tests cover:
 *   (a) Happy path: successful AI response renders the chart renderer.
 *   (b) 422 fallback: friendly message shown; onFallback callback invoked.
 *   (c) 503 error: retry message shown; chart is NOT rendered.
 *   (d) Loading state: "Generating…" button label and status text shown.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import { NLChartPanel } from "@/components/chart/NLChartPanel";
import { NLChartError } from "@/api/client";
import type { NLChartResponse } from "@/types/api";

// ---------------------------------------------------------------------------
// Mock the hook module so no real fetch calls are made.
// ---------------------------------------------------------------------------

vi.mock("@/api/hooks", () => ({
  useNLChart: vi.fn(),
}));

// Mock ChartRenderer so we don't need a DOM canvas / ECharts in jsdom.
vi.mock("@/components/chart/ChartRenderer", () => ({
  ChartRenderer: ({
    title,
    "data-testid": testId,
  }: {
    title?: string;
    "data-testid"?: string;
  }) => (
    <div
      role="img"
      aria-label={title ?? "chart"}
      data-testid={testId ?? "chart-renderer"}
    />
  ),
}));

// ---------------------------------------------------------------------------
// Import after mocks are registered.
// ---------------------------------------------------------------------------

import { useNLChart } from "@/api/hooks";

// Typed cast so we can configure mock return values per test.
const mockUseNLChart = vi.mocked(useNLChart);

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const validResponse: NLChartResponse = {
  spec: {
    version: "1",
    type: "bar",
    query: { dataset_id: null, metric_refs: ["total_sales"] },
    encoding: {
      x: "region",
      series: [{ field: "total_sales", name: "Total Sales" }],
    },
    options: { title: "Total sales by region" },
  },
  data: {
    columns: ["region", "total_sales"],
    rows: [
      ["North", 4200],
      ["South", 3100],
    ],
    row_count: 2,
  },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Build a minimal useMutation-like return value.
 * `mutate` is replaced by the passed spy so tests can simulate its behaviour.
 */
function makeMutationReturn(overrides: {
  isPending?: boolean;
  error?: Error | null;
  mutate?: (...args: unknown[]) => void;
  reset?: () => void;
}) {
  return {
    isPending: overrides.isPending ?? false,
    error: overrides.error ?? null,
    mutate: overrides.mutate ?? vi.fn(),
    reset: overrides.reset ?? vi.fn(),
    // Other TanStack Query mutation fields the component does not use:
    data: undefined,
    isError: overrides.error !== null,
    isSuccess: false,
    isIdle: !overrides.isPending,
    mutateAsync: vi.fn(),
    status: "idle" as const,
    variables: undefined,
    context: undefined,
    failureCount: 0,
    failureReason: null,
    submittedAt: 0,
  };
}

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  // Default: idle mutation.
  mockUseNLChart.mockReturnValue(
    // @ts-expect-error: we return a partial that satisfies the component's usage
    makeMutationReturn({})
  );
});

afterEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("NLChartPanel — happy path (AI chart rendered)", () => {
  it("(a) renders ChartRenderer with spec+data when mutation succeeds", async () => {
    // Simulate a mutation that immediately calls onSuccess.
    const mutateSpy = vi.fn(
      (_vars: unknown, callbacks?: { onSuccess?: (r: NLChartResponse) => void }) => {
        callbacks?.onSuccess?.(validResponse);
      }
    );

    mockUseNLChart.mockReturnValue(
      // @ts-expect-error: partial mock
      makeMutationReturn({ mutate: mutateSpy })
    );

    render(<NLChartPanel />);

    const textarea = screen.getByRole("textbox", { name: /chart description/i });
    fireEvent.change(textarea, {
      target: { value: "total sales by region as a bar chart" },
    });

    const submitBtn = screen.getByRole("button", { name: /generate chart/i });
    fireEvent.click(submitBtn);

    // The mutate spy is called synchronously with our test value.
    expect(mutateSpy).toHaveBeenCalledWith(
      { request: "total sales by region as a bar chart" },
      expect.objectContaining({ onSuccess: expect.any(Function) })
    );

    // After onSuccess fires, the ChartRenderer should be present.
    await waitFor(() => {
      expect(screen.getByRole("img", { name: /total sales by region/i })).toBeInTheDocument();
    });

    // Row count is shown.
    expect(screen.getByText(/2 rows returned/i)).toBeInTheDocument();
  });
});

describe("NLChartPanel — 422 fallback", () => {
  it("(b) shows fallback message and calls onFallback when mutation returns 422 error", async () => {
    const ungroundableError = new NLChartError(
      "ungroundable",
      "No grounded metric for that description"
    );

    const onFallback = vi.fn();

    const mutateSpy = vi.fn(
      (_vars: unknown, callbacks?: { onError?: (e: Error) => void }) => {
        callbacks?.onError?.(ungroundableError);
      }
    );

    mockUseNLChart.mockReturnValue(
      // @ts-expect-error: partial mock
      makeMutationReturn({ error: ungroundableError, mutate: mutateSpy })
    );

    render(<NLChartPanel onFallback={onFallback} />);

    const textarea = screen.getByRole("textbox", { name: /chart description/i });
    fireEvent.change(textarea, { target: { value: "nonsense gobbledygook" } });
    fireEvent.click(screen.getByRole("button", { name: /generate chart/i }));

    // onFallback must have been called.
    expect(onFallback).toHaveBeenCalledOnce();

    // The fallback message is visible.
    await waitFor(() => {
      expect(
        screen.getByText(/couldn't be turned into a valid chart|could not generate/i)
      ).toBeInTheDocument();
    });

    // No chart renderer is shown.
    expect(screen.queryByTestId("chart-renderer")).not.toBeInTheDocument();
  });

  it("(b) fallback message tells the user to try rephrasing or use manual builder", async () => {
    const ungroundableError = new NLChartError("ungroundable", "");

    mockUseNLChart.mockReturnValue(
      // @ts-expect-error: partial mock
      makeMutationReturn({ error: ungroundableError })
    );

    render(<NLChartPanel />);

    await waitFor(() => {
      expect(
        screen.getByText(/rephras|manually/i)
      ).toBeInTheDocument();
    });
  });
});

describe("NLChartPanel — 503 service unavailable", () => {
  it("(c) shows retry message and no chart on service_unavailable error", async () => {
    const serviceError = new NLChartError(
      "service_unavailable",
      "Service Unavailable"
    );

    mockUseNLChart.mockReturnValue(
      // @ts-expect-error: partial mock
      makeMutationReturn({ error: serviceError })
    );

    render(<NLChartPanel />);

    // The AlertTitle is a heading-level element — query by role to avoid
    // matching both the title and the description.
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: /service unavailable/i })
      ).toBeInTheDocument();
    });

    // No chart renderer shown on error.
    expect(screen.queryByTestId("chart-renderer")).not.toBeInTheDocument();
  });
});

describe("NLChartPanel — loading state", () => {
  it("(d) shows loading text and disables submit while isPending", () => {
    mockUseNLChart.mockReturnValue(
      // @ts-expect-error: partial mock
      makeMutationReturn({ isPending: true })
    );

    render(<NLChartPanel />);

    // Button label changes to "Generating…".
    expect(
      screen.getByRole("button", { name: /generating/i })
    ).toBeDisabled();

    // Status text is present.
    expect(
      screen.getByRole("status")
    ).toBeInTheDocument();
  });
});

describe("NLChartPanel — contextual prompt suggestions", () => {
  it("clicking a suggestion fills the textarea and enables submit", () => {
    mockUseNLChart.mockReturnValue(
      // @ts-expect-error: partial mock
      makeMutationReturn({})
    );

    render(<NLChartPanel suggestions={["Revenue by quarter as a line chart"]} />);

    // Submit starts disabled (empty prompt).
    expect(screen.getByRole("button", { name: /generate chart/i })).toBeDisabled();

    fireEvent.click(
      screen.getByRole("button", { name: /revenue by quarter as a line chart/i })
    );

    const textarea = screen.getByRole("textbox", {
      name: /chart description/i,
    }) as HTMLTextAreaElement;
    expect(textarea.value).toBe("Revenue by quarter as a line chart");
    expect(screen.getByRole("button", { name: /generate chart/i })).not.toBeDisabled();
  });
});

describe("NLChartPanel — input validation", () => {
  it("submit button is disabled when the prompt is empty", () => {
    mockUseNLChart.mockReturnValue(
      // @ts-expect-error: partial mock
      makeMutationReturn({})
    );

    render(<NLChartPanel />);

    expect(
      screen.getByRole("button", { name: /generate chart/i })
    ).toBeDisabled();
  });

  it("submit button is enabled once the user types something", () => {
    mockUseNLChart.mockReturnValue(
      // @ts-expect-error: partial mock
      makeMutationReturn({})
    );

    render(<NLChartPanel />);

    fireEvent.change(
      screen.getByRole("textbox", { name: /chart description/i }),
      { target: { value: "revenue by quarter" } }
    );

    expect(
      screen.getByRole("button", { name: /generate chart/i })
    ).not.toBeDisabled();
  });
});
