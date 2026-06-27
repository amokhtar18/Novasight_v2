import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { ComponentsGallery } from "@/pages/dev/ComponentsGallery";

describe("ComponentsGallery", () => {
  it("renders the component catalog with the primitive sections", () => {
    render(<ComponentsGallery />);
    expect(
      screen.getByRole("heading", { name: /component gallery/i })
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /^button$/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /^field$/i })).toBeInTheDocument();
  });

  it("renders a loading-state button (aria-busy)", () => {
    render(<ComponentsGallery />);
    const busy = screen
      .getAllByRole("button")
      .filter((b) => b.getAttribute("aria-busy") === "true");
    expect(busy.length).toBeGreaterThan(0);
  });
});
