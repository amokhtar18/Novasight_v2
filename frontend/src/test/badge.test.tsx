import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { Badge } from "@/components/ui/badge";

describe("Badge", () => {
  it("uses the shared focus ring (offset)", () => {
    render(<Badge>New</Badge>);
    expect(screen.getByText("New")).toHaveClass("focus-visible:ring-offset-2");
  });

  it("keeps its semantic variants", () => {
    render(<Badge variant="success">ok</Badge>);
    expect(screen.getByText("ok")).toHaveClass("text-success");
  });
});
