/**
 * Tests for useSemanticBuilder.loadSpec — restoring a saved ChartSpec back into
 * builder state (#9 / superset-parity slice A).
 *
 * Approach: renderHook driving the exported useSemanticBuilder hook with all
 * API dependencies mocked, so no network call is needed. Covers that loadSpec
 * correctly restores filters, order, limit, and date_range from a spec.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";

import type { ChartSpec, SemanticModelRead, QueryResponse } from "@/types/api";

// ---------------------------------------------------------------------------
// Mock all API hooks — identical pattern to builderSemantic.test.tsx
// ---------------------------------------------------------------------------

vi.mock("@/api/hooks", () => ({
  useSemanticModels: vi.fn(),
  useSemanticQuery: vi.fn(),
  useCreateChart: vi.fn(),
  useCharts: vi.fn(),
  useDeleteChart: vi.fn(),
}));

vi.mock("@/components/chart/ChartRenderer", () => ({
  ChartRenderer: () => null,
}));
vi.mock("@/components/chart/NLChartPanel", () => ({
  NLChartPanel: () => null,
}));
vi.mock("@/components/dashboard/AddToDashboard", () => ({
  AddToDashboard: () => null,
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { useSemanticModels, useSemanticQuery, useCreateChart, useCharts, useDeleteChart } from "@/api/hooks";
import { useSemanticBuilder } from "@/pages/Builder";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const model: SemanticModelRead = {
  name: "regional_sales",
  title: "Regional Sales",
  measures: [{ name: "regional_sales.total_amount", title: "Total Amount", type: "number" }],
  dimensions: [{ name: "regional_sales.region", title: "Region", type: "string" }],
};

const emptyQuery: QueryResponse = {
  columns: [],
  rows: [],
  row_count: 0,
};

function idleQuery<T>(data: T) {
  return { data, isLoading: false, isError: false, error: null };
}

function idleMutation() {
  return { mutate: vi.fn(), isPending: false };
}

// A saved spec that carries filters, order, limit, and a time dimension with date_range.
const savedSpec: ChartSpec = {
  version: "1",
  type: "bar",
  query: {
    metric_refs: ["regional_sales.total_amount"],
    dimensions: [],
    time_dimensions: [
      {
        dimension: "regional_sales.region",
        granularity: "month",
        date_range: "last_30_days",
      },
    ],
    filters: [
      { member: "regional_sales.region", operator: "equals", values: ["west"] },
    ],
    order: { "regional_sales.total_amount": "desc" },
    limit: 25,
  },
  encoding: {
    x: "regional_sales.region.month",
    series: [{ field: "regional_sales.total_amount", name: "Total Amount" }],
  },
  options: { title: "Test spec" },
};

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  // @ts-expect-error partial mock
  vi.mocked(useSemanticModels).mockReturnValue(idleQuery([model]));
  // @ts-expect-error partial mock
  vi.mocked(useSemanticQuery).mockReturnValue(idleQuery(emptyQuery));
  // @ts-expect-error partial mock
  vi.mocked(useCreateChart).mockReturnValue(idleMutation());
  // @ts-expect-error partial mock
  vi.mocked(useCharts).mockReturnValue(idleQuery([]));
  // @ts-expect-error partial mock
  vi.mocked(useDeleteChart).mockReturnValue(idleMutation());
});

afterEach(() => vi.clearAllMocks());

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useSemanticBuilder.loadSpec — restores spec into builder state", () => {
  it("restores filters from the saved spec", () => {
    const { result } = renderHook(() => useSemanticBuilder());

    act(() => {
      result.current.loadSpec(savedSpec);
    });

    expect(result.current.filters).toEqual([
      { member: "regional_sales.region", operator: "equals", values: ["west"] },
    ]);
  });

  it("restores orderBy from the saved spec", () => {
    const { result } = renderHook(() => useSemanticBuilder());

    act(() => {
      result.current.loadSpec(savedSpec);
    });

    expect(result.current.orderBy).toEqual({
      member: "regional_sales.total_amount",
      dir: "desc",
    });
  });

  it("restores rowLimit from the saved spec", () => {
    const { result } = renderHook(() => useSemanticBuilder());

    act(() => {
      result.current.loadSpec(savedSpec);
    });

    expect(result.current.rowLimit).toBe(25);
  });

  it("restores dateRange from the time_dimensions of the saved spec", () => {
    const { result } = renderHook(() => useSemanticBuilder());

    act(() => {
      result.current.loadSpec(savedSpec);
    });

    expect(result.current.dateRange).toBe("last_30_days");
  });
});
