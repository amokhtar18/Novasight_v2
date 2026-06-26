import { describe, expect, it } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
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

  it("closes the menu after an action is selected", () => {
    render(<ChartActionsMenu spec={specOfType("bar")} data={data} title="Sales" />);
    fireEvent.click(screen.getByRole("button", { name: /chart actions/i }));
    expect(screen.getByRole("menu")).toBeInTheDocument();
    fireEvent.click(screen.getByText(/view query/i));
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("closes the menu on Escape key", () => {
    render(<ChartActionsMenu spec={specOfType("bar")} data={data} title="Sales" />);
    fireEvent.click(screen.getByRole("button", { name: /chart actions/i }));
    expect(screen.getByRole("menu")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("closes the menu on outside mousedown", () => {
    const { container } = render(
      <div>
        <div data-testid="outside">outside</div>
        <ChartActionsMenu spec={specOfType("bar")} data={data} title="Sales" />
      </div>
    );
    fireEvent.click(screen.getByRole("button", { name: /chart actions/i }));
    expect(screen.getByRole("menu")).toBeInTheDocument();
    fireEvent.mouseDown(screen.getByTestId("outside"));
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    void container;
  });

  it("does not close the menu on mousedown inside the container", () => {
    render(<ChartActionsMenu spec={specOfType("bar")} data={data} title="Sales" />);
    fireEvent.click(screen.getByRole("button", { name: /chart actions/i }));
    const menu = screen.getByRole("menu");
    fireEvent.mouseDown(within(menu).getByText(/view as table/i));
    expect(screen.getByRole("menu")).toBeInTheDocument();
  });
});
