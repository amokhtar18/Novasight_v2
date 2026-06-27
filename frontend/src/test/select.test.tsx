import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { Select } from "@/components/ui/select";

function options() {
  return (
    <>
      <option value="a">A</option>
      <option value="b">B</option>
    </>
  );
}

describe("Select", () => {
  it("defaults to the md (h-9) control height", () => {
    render(
      <Select aria-label="pick" defaultValue="a">
        {options()}
      </Select>
    );
    expect(screen.getByLabelText("pick")).toHaveClass("h-[var(--control-h-md)]");
  });

  it("applies the sm height when size=sm", () => {
    render(<Select aria-label="pick" size="sm" defaultValue="a">{options()}</Select>);
    expect(screen.getByLabelText("pick")).toHaveClass("h-[var(--control-h-sm)]");
  });

  it("applies the lg height when size=lg", () => {
    render(<Select aria-label="pick" size="lg" defaultValue="a">{options()}</Select>);
    expect(screen.getByLabelText("pick")).toHaveClass("h-[var(--control-h-lg)]");
  });

  it("sets aria-invalid when invalid", () => {
    render(
      <Select aria-label="pick" invalid defaultValue="a">
        {options()}
      </Select>
    );
    expect(screen.getByLabelText("pick")).toHaveAttribute("aria-invalid", "true");
  });

  it("renders its options", () => {
    render(
      <Select aria-label="pick" defaultValue="a">
        {options()}
      </Select>
    );
    expect(screen.getByRole("option", { name: "A" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "B" })).toBeInTheDocument();
  });
});
