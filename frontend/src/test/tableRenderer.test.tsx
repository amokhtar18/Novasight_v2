/**
 * Tests for TableRenderer:
 *   - renders headers + rows from a QueryResponse;
 *   - formats null cells;
 *   - follows the spec's encoding order/labels when a spec is supplied.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { TableRenderer } from "@/components/chart/TableRenderer";
import type { ChartSpec, QueryResponse } from "@/types/api";

const data: QueryResponse = {
  columns: ["category", "total"],
  rows: [
    ["alpha", 10],
    ["beta", null],
  ],
  row_count: 2,
};

describe("TableRenderer", () => {
  it("renders humanized headers and the row values", () => {
    render(<TableRenderer data={data} />);
    expect(screen.getByText("Category")).toBeInTheDocument();
    expect(screen.getByText("Total")).toBeInTheDocument();
    expect(screen.getByText("alpha")).toBeInTheDocument();
    // 10 is localized; just assert presence of the cell text.
    expect(screen.getByText("10")).toBeInTheDocument();
  });

  it("renders null cells as an em dash", () => {
    render(<TableRenderer data={data} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("respects spec encoding order when provided", () => {
    const spec: ChartSpec = {
      version: "1",
      type: "table",
      query: {},
      encoding: { x: "total", series: [{ field: "category" }] },
    };
    render(<TableRenderer data={data} spec={spec} />);
    const headers = screen.getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual(["Total", "Category"]);
  });
});
