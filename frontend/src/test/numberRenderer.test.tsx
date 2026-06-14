/**
 * Tests for NumberRenderer (the "big number" KPI tile):
 *   - sums the first series across rows and formats the total;
 *   - shows the series label and the optional title;
 *   - renders an em dash when the series column is missing.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { NumberRenderer } from "@/components/chart/NumberRenderer";
import type { ChartSpec, QueryResponse } from "@/types/api";

const data: QueryResponse = {
  columns: ["region", "revenue"],
  rows: [
    ["west", 1000],
    ["east", 240],
  ],
  row_count: 2,
};

function spec(over: Partial<ChartSpec> = {}): ChartSpec {
  return {
    version: "1",
    type: "number",
    query: { metric_refs: ["revenue"] },
    encoding: { series: [{ field: "revenue", name: "Revenue" }] },
    ...over,
  };
}

describe("NumberRenderer", () => {
  it("shows the total of the first series across rows", () => {
    render(<NumberRenderer spec={spec()} data={data} />);
    // 1000 + 240 = 1240, localized.
    expect(screen.getByText("1,240")).toBeInTheDocument();
    expect(screen.getByText("Revenue")).toBeInTheDocument();
  });

  it("shows the optional title", () => {
    render(<NumberRenderer spec={spec({ options: { title: "Total revenue" } })} data={data} />);
    expect(screen.getByText("Total revenue")).toBeInTheDocument();
  });

  it("renders an em dash when the series column is absent", () => {
    const missing: ChartSpec = spec({
      encoding: { series: [{ field: "not_a_column", name: "Missing" }] },
    });
    render(<NumberRenderer spec={missing} data={data} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
