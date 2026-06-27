import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { DropdownMenu, DropdownItem } from "@/components/ui/dropdown-menu";

function Harness() {
  return (
    <DropdownMenu trigger={<span>Open</span>} label="menu">
      <DropdownItem>Item</DropdownItem>
    </DropdownMenu>
  );
}

describe("DropdownMenu", () => {
  it("trigger uses the shared focus ring (offset)", () => {
    render(<Harness />);
    expect(screen.getByRole("button", { name: "menu" })).toHaveClass(
      "focus-visible:ring-offset-2"
    );
  });

  it("opens the menu with token-driven stacking + elevation", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "menu" }));
    const menu = screen.getByRole("menu");
    expect(menu).toHaveClass("z-[var(--z-dropdown)]");
    expect(menu).toHaveClass("shadow-[var(--elevation-3)]");
  });

  it("closes on item activation (behavior preserved)", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "menu" }));
    await user.click(screen.getByRole("menuitem", { name: "Item" }));
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
});
