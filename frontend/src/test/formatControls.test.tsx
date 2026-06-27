import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { FormatControls, FAMILY_FOR_TYPE } from "@/components/chart/format";
import type { ChartOptions } from "@/types/api";

const noop = () => {};
const base: ChartOptions = {};

describe("FormatControls type-awareness", () => {
  it("maps each chart type to the right family", () => {
    expect(FAMILY_FOR_TYPE.bar).toBe("cartesian");
    expect(FAMILY_FOR_TYPE.donut).toBe("pie");
    expect(FAMILY_FOR_TYPE.gauge).toBe("gauge");
    expect(FAMILY_FOR_TYPE.table).toBeNull();
  });
  it("shows cartesian section for bar, not pie", () => {
    render(<FormatControls options={base} setOptions={noop} chartType="bar" />);
    expect(screen.getByText(/stacked/i)).toBeInTheDocument();
    expect(screen.queryByText(/donut hole|inner radius/i)).not.toBeInTheDocument();
  });
  it("shows pie section for donut, not cartesian stacked", () => {
    render(<FormatControls options={base} setOptions={noop} chartType="donut" />);
    expect(screen.getByText(/inner radius/i)).toBeInTheDocument();
    expect(screen.queryByText(/^stacked$/i)).not.toBeInTheDocument();
  });
  it("renders the cartesian 'Stacked' toggle as the hardened Checkbox", () => {
    render(<FormatControls options={base} setOptions={noop} chartType="bar" />);
    expect(screen.getByRole("checkbox", { name: "Stacked" })).toHaveClass(
      "accent-primary"
    );
  });
});
