/**
 * Tests for UsersPanel: renders the tenant's users and exposes create/delete.
 * The data hooks are mocked so the panel is tested in isolation (no network).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

const mutate = vi.fn();

vi.mock("@/api/hooks", () => ({
  useUsers: () => ({
    data: [
      { id: "1", email: "a@local", name: "Ann", roles: ["superuser"], is_active: true },
      { id: "2", email: "b@local", name: null, roles: [], is_active: false },
    ],
    isLoading: false,
    isError: false,
  }),
  useCreateUser: () => ({ mutate, isPending: false }),
  useUpdateUser: () => ({ mutate, isPending: false }),
  useDeleteUser: () => ({ mutate, isPending: false }),
}));

vi.mock("@/lib/identity", () => ({
  useIdentity: () => ({ isPlatformAdmin: false }),
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { UsersPanel } from "@/components/admin/UsersPanel";

beforeEach(() => {
  mutate.mockClear();
});

describe("UsersPanel", () => {
  it("renders the tenant's users", () => {
    render(<UsersPanel />);
    expect(screen.getByText("Ann")).toBeInTheDocument();
    expect(screen.getByText("a@local")).toBeInTheDocument();
    // The nameless user falls back to its email in the name slot, so it appears
    // in both the name and email cells.
    expect(screen.getAllByText("b@local").length).toBeGreaterThanOrEqual(1);
    // Inactive user shows a badge instead of an active toggle.
    expect(screen.getByText("inactive")).toBeInTheDocument();
  });

  it("opens the create dialog from the New user button", () => {
    render(<UsersPanel />);
    fireEvent.click(screen.getByRole("button", { name: /new user/i }));
    expect(screen.getByText("Create user")).toBeInTheDocument();
  });

  it("does not show the platform-admin column for a non-platform-admin", () => {
    render(<UsersPanel />);
    expect(screen.queryByText("Platform admin")).not.toBeInTheDocument();
  });
});
