import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { Checkbox } from "@/components/ui/checkbox";

describe("Checkbox", () => {
  it("uses the shared focus ring (offset)", () => {
    render(<Checkbox aria-label="agree" />);
    expect(screen.getByLabelText("agree")).toHaveClass("focus-visible:ring-offset-2");
  });
});
