import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { TileSizeControl } from "@/components/dashboard/TileSizeControl";

describe("TileSizeControl", () => {
  it("opens via a keyboard-focusable button and emits new width/height", () => {
    const onResize = vi.fn();
    render(<TileSizeControl title="Revenue" w={6} h={4} onResize={onResize} />);

    fireEvent.click(screen.getByRole("button", { name: "Size of Revenue" }));
    fireEvent.change(screen.getByLabelText("Width of Revenue"), { target: { value: "8" } });
    expect(onResize).toHaveBeenCalledWith(8, 4);

    fireEvent.change(screen.getByLabelText("Height of Revenue"), { target: { value: "5" } });
    expect(onResize).toHaveBeenCalledWith(6, 5);
  });

  it("clamps out-of-range values to 1..12", () => {
    const onResize = vi.fn();
    render(<TileSizeControl title="Revenue" w={6} h={4} onResize={onResize} />);
    fireEvent.click(screen.getByRole("button", { name: "Size of Revenue" }));
    fireEvent.change(screen.getByLabelText("Width of Revenue"), { target: { value: "99" } });
    expect(onResize).toHaveBeenCalledWith(12, 4);
  });
});
