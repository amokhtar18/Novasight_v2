import { describe, expect, it } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ChartActionsMenu } from "@/components/chart/ChartActionsMenu";
import type { ChartSpec, QueryResponse } from "@/types/api";

const data: QueryResponse = { columns: ["region", "sales"], rows: [["west", 100]], row_count: 1 };

function specOfType(type: ChartSpec["type"]): ChartSpec {
  return {
    version: "1",
    type,
    query: { metric_refs: ["s.sales"], dimensions: ["s.region"] },
    encoding: { x: "s.region", series: [{ field: "s.sales" }] },
  };
}

describe("ChartActionsMenu", () => {
  it("offers View as table and View query", () => {
    render(<ChartActionsMenu spec={specOfType("bar")} data={data} title="Sales" />);
    fireEvent.click(screen.getByRole("button", { name: /chart actions/i }));
    expect(screen.getByText(/view as table/i)).toBeInTheDocument();
    expect(screen.getByText(/view query/i)).toBeInTheDocument();
    expect(screen.getByText(/download csv/i)).toBeInTheDocument();
  });

  it("hides Download PNG for table charts", () => {
    render(<ChartActionsMenu spec={specOfType("table")} data={data} title="T" />);
    fireEvent.click(screen.getByRole("button", { name: /chart actions/i }));
    expect(screen.queryByText(/download png/i)).not.toBeInTheDocument();
  });

  it("shows the semantic query (not SQL) in View query", () => {
    render(<ChartActionsMenu spec={specOfType("bar")} data={data} title="Sales" />);
    fireEvent.click(screen.getByRole("button", { name: /chart actions/i }));
    fireEvent.click(screen.getByText(/view query/i));
    expect(screen.getByText(/metric_refs/)).toBeInTheDocument();
  });
});
