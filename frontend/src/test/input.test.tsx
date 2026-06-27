import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { Input } from "@/components/ui/input";

describe("Input", () => {
  it("defaults to the md (h-9) control height", () => {
    render(<Input aria-label="name" />);
    expect(screen.getByLabelText("name")).toHaveClass("h-[var(--control-h-md)]");
  });

  it("applies the sm height when size=sm", () => {
    render(<Input aria-label="name" size="sm" />);
    expect(screen.getByLabelText("name")).toHaveClass("h-[var(--control-h-sm)]");
  });

  it("applies the lg height when size=lg", () => {
    render(<Input aria-label="name" size="lg" />);
    expect(screen.getByLabelText("name")).toHaveClass("h-[var(--control-h-lg)]");
  });

  it("sets aria-invalid when invalid", () => {
    render(<Input aria-label="name" invalid />);
    expect(screen.getByLabelText("name")).toHaveAttribute("aria-invalid", "true");
  });

  it("is not aria-invalid by default", () => {
    render(<Input aria-label="name" />);
    expect(screen.getByLabelText("name")).not.toHaveAttribute("aria-invalid");
  });
});
