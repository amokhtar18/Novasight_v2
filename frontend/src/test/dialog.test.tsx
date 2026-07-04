/**
 * Tests for the Dialog primitive's focus management.
 *
 * Regression: the focus effect must run only when the dialog opens/closes, not on
 * every parent re-render. Pages pass an inline `onOpenChange` (new identity each
 * render), so typing into a field inside the dialog used to re-run the effect and
 * steal focus to the Close button after every keystroke (cursor "jumped").
 */

import { useState } from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { Dialog } from "@/components/ui/dialog";

/** Mirrors real usage: controlled field + inline onOpenChange that re-renders. */
function Harness() {
  const [open, setOpen] = useState(true);
  const [value, setValue] = useState("");
  return (
    <Dialog open={open} onOpenChange={(o) => setOpen(o)}>
      <input
        aria-label="field"
        value={value}
        onChange={(e) => setValue(e.target.value)}
      />
    </Dialog>
  );
}

describe("Dialog focus management", () => {
  it("keeps focus on a field while typing across re-renders", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    const input = screen.getByLabelText<HTMLInputElement>("field");
    input.focus();
    expect(input).toHaveFocus();

    await user.keyboard("hello world");

    expect(input).toHaveValue("hello world");
    expect(input).toHaveFocus();
  });
});
