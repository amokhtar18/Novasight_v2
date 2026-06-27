import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { Button } from "@/components/ui/button";

describe("Button", () => {
  it("renders a md (h-9) default height", () => {
    render(<Button>Save</Button>);
    expect(screen.getByRole("button", { name: "Save" })).toHaveClass(
      "h-[var(--control-h-md)]"
    );
  });

  it("shows a spinner, marks aria-busy, and disables while loading", () => {
    render(<Button loading>Save</Button>);
    const button = screen.getByRole("button", { name: /save/i });
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(button).toBeDisabled();
    // role=status comes from <Spinner> — proves the spinner is rendered.
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("keeps its label in the DOM while loading (width preserved, zero shift)", () => {
    render(<Button loading>Save</Button>);
    expect(screen.getByText("Save")).toBeInTheDocument();
  });

  it("does not fire onClick while loading", async () => {
    let clicks = 0;
    const user = userEvent.setup();
    render(
      <Button loading onClick={() => (clicks += 1)}>
        Save
      </Button>
    );
    await user.click(screen.getByRole("button"));
    expect(clicks).toBe(0);
  });

  it("renders as a child element when asChild is set (no spinner injected)", () => {
    render(
      <Button asChild>
        <a href="/x">link</a>
      </Button>
    );
    const link = screen.getByRole("link", { name: "link" });
    expect(link).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("uses a custom loadingLabel for the spinner", () => {
    render(<Button loading loadingLabel="Saving…">Save</Button>);
    expect(screen.getByRole("status")).toHaveAttribute("aria-label", "Saving…");
  });
});
