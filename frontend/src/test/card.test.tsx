import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { Card } from "@/components/ui/card";

describe("Card", () => {
  it("defaults to elevation 1 (sm)", () => {
    render(<Card data-testid="card">body</Card>);
    expect(screen.getByTestId("card")).toHaveClass("shadow-[var(--elevation-1)]");
  });

  it("applies a higher elevation when requested", () => {
    render(
      <Card data-testid="card" elevation="lg">
        body
      </Card>
    );
    expect(screen.getByTestId("card")).toHaveClass("shadow-[var(--elevation-3)]");
  });

  it("renders no shadow when elevation=none", () => {
    render(
      <Card data-testid="card" elevation="none">
        body
      </Card>
    );
    const el = screen.getByTestId("card");
    expect(el).not.toHaveClass("shadow-[var(--elevation-1)]");
  });
});
