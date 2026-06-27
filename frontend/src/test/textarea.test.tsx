import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { Textarea } from "@/components/ui/textarea";

describe("Textarea", () => {
  it("renders with a sane default row count", () => {
    render(<Textarea aria-label="notes" />);
    expect(screen.getByLabelText("notes")).toHaveAttribute("rows", "4");
  });

  it("sets aria-invalid when invalid", () => {
    render(<Textarea aria-label="notes" invalid />);
    expect(screen.getByLabelText("notes")).toHaveAttribute("aria-invalid", "true");
  });

  it("omits aria-invalid when not invalid", () => {
    render(<Textarea aria-label="notes" />);
    expect(screen.getByLabelText("notes")).not.toHaveAttribute("aria-invalid");
  });

  it("accepts typed input", async () => {
    const user = userEvent.setup();
    render(<Textarea aria-label="notes" />);
    const el = screen.getByLabelText<HTMLTextAreaElement>("notes");
    await user.type(el, "hello");
    expect(el).toHaveValue("hello");
  });
});
