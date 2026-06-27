import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { Switch } from "@/components/ui/switch";

describe("Switch", () => {
  it("uses the shared focus ring (offset)", () => {
    render(<Switch checked={false} onCheckedChange={() => {}} aria-label="toggle" />);
    expect(screen.getByRole("switch")).toHaveClass("focus-visible:ring-offset-2");
  });

  it("toggles on click (behavior preserved)", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<Switch checked={false} onCheckedChange={onChange} aria-label="toggle" />);
    await user.click(screen.getByRole("switch"));
    expect(onChange).toHaveBeenCalledWith(true);
  });
});
