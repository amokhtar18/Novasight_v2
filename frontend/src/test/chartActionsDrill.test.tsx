// frontend/src/test/chartActionsDrill.test.tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { createRef } from "react";

import { ChartActionsMenu } from "@/components/chart/ChartActionsMenu";
import type { ChartRendererHandle } from "@/components/chart/ChartRenderer";
import type { ChartSpec, QueryResponse } from "@/types/api";

const spec: ChartSpec = {
  type: "bar",
  query: { metric_refs: ["regional_sales.total_amount"] },
  encoding: { x: "regional_sales.region", series: [{ field: "regional_sales.total_amount" }] },
};
const data: QueryResponse = {
  columns: ["regional_sales.region", "regional_sales.total_amount"],
  rows: [["west", 1]],
  row_count: 1,
};

describe("ChartActionsMenu drill", () => {
  it("shows drill entries when handlers are provided and fires them", () => {
    const onDrillBy = vi.fn();
    const onDrillToDetail = vi.fn();
    const ref = createRef<ChartRendererHandle>();
    render(
      <ChartActionsMenu
        spec={spec}
        data={data}
        chartHandle={ref}
        title="C"
        onDrillBy={onDrillBy}
        onDrillToDetail={onDrillToDetail}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /chart actions/i }));
    fireEvent.click(screen.getByText(/drill by/i));
    expect(onDrillBy).toHaveBeenCalled();
  });

  it("fires onDrillToDetail when 'Drill to detail…' is clicked", () => {
    const onDrillBy = vi.fn();
    const onDrillToDetail = vi.fn();
    const ref = createRef<ChartRendererHandle>();
    render(
      <ChartActionsMenu
        spec={spec}
        data={data}
        chartHandle={ref}
        title="C"
        onDrillBy={onDrillBy}
        onDrillToDetail={onDrillToDetail}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /chart actions/i }));
    fireEvent.click(screen.getByText(/drill to detail/i));
    expect(onDrillToDetail).toHaveBeenCalled();
  });

  it("hides drill entries when handlers are absent", () => {
    const ref = createRef<ChartRendererHandle>();
    render(<ChartActionsMenu spec={spec} data={data} chartHandle={ref} title="C" />);
    fireEvent.click(screen.getByRole("button", { name: /chart actions/i }));
    expect(screen.queryByText(/drill by/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/drill to detail/i)).not.toBeInTheDocument();
  });

  it("hides drill entries for non-semantic charts (no metric_refs)", () => {
    const nonSemanticSpec: ChartSpec = {
      type: "bar",
      query: { metric_refs: [] },
      encoding: { x: "region", series: [{ field: "sales" }] },
    };
    const onDrillBy = vi.fn();
    const onDrillToDetail = vi.fn();
    const ref = createRef<ChartRendererHandle>();
    render(
      <ChartActionsMenu
        spec={nonSemanticSpec}
        data={data}
        chartHandle={ref}
        title="C"
        onDrillBy={onDrillBy}
        onDrillToDetail={onDrillToDetail}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /chart actions/i }));
    expect(screen.queryByText(/drill by/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/drill to detail/i)).not.toBeInTheDocument();
  });

  it("hides 'Drill by…' for number chart type", () => {
    const numberSpec: ChartSpec = {
      type: "number",
      query: { metric_refs: ["regional_sales.total_amount"] },
      encoding: { x: "regional_sales.region", series: [{ field: "regional_sales.total_amount" }] },
    };
    const onDrillBy = vi.fn();
    const onDrillToDetail = vi.fn();
    const ref = createRef<ChartRendererHandle>();
    render(
      <ChartActionsMenu
        spec={numberSpec}
        data={data}
        chartHandle={ref}
        title="C"
        onDrillBy={onDrillBy}
        onDrillToDetail={onDrillToDetail}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /chart actions/i }));
    expect(screen.queryByText(/drill by/i)).not.toBeInTheDocument();
    // Drill to detail is still shown for number charts
    expect(screen.getByText(/drill to detail/i)).toBeInTheDocument();
  });

  it("hides 'Drill by…' for table chart type", () => {
    const tableSpec: ChartSpec = {
      type: "table",
      query: { metric_refs: ["regional_sales.total_amount"] },
      encoding: { x: "regional_sales.region", series: [{ field: "regional_sales.total_amount" }] },
    };
    const onDrillBy = vi.fn();
    const onDrillToDetail = vi.fn();
    const ref = createRef<ChartRendererHandle>();
    render(
      <ChartActionsMenu
        spec={tableSpec}
        data={data}
        chartHandle={ref}
        title="C"
        onDrillBy={onDrillBy}
        onDrillToDetail={onDrillToDetail}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /chart actions/i }));
    expect(screen.queryByText(/drill by/i)).not.toBeInTheDocument();
    // Drill to detail is still shown for table charts
    expect(screen.getByText(/drill to detail/i)).toBeInTheDocument();
  });
});
