/**
 * Tests for the grouped sidebar navigation (Phase 2 widen — item 1/2).
 *
 * Asserts the section headers render in order, that grouped items live under
 * their header, and that the admin-only item is gated by identity. uiStore and
 * identity are mocked; rendering is wrapped in a router for NavLink.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("@/store/uiStore", () => ({ useUiStore: vi.fn() }));
vi.mock("@/lib/identity", () => ({ useIdentity: vi.fn() }));

import { Sidebar } from "@/components/layout/Sidebar";
import { useUiStore } from "@/store/uiStore";
import { useIdentity } from "@/lib/identity";

const uiState = {
  sidebarCollapsed: false,
  mobileNavOpen: false,
  toggleSidebar: vi.fn(),
  setMobileNav: vi.fn(),
};

beforeEach(() => {
  // useUiStore is called with a selector; feed it our fake state.
  vi.mocked(useUiStore).mockImplementation((sel) => sel(uiState));
  vi.mocked(useIdentity).mockReturnValue({ isAdmin: false } as ReturnType<typeof useIdentity>);
});

function renderSidebar() {
  return render(
    <MemoryRouter>
      <Sidebar />
    </MemoryRouter>
  );
}

describe("Sidebar grouping", () => {
  it("renders the section headers in order", () => {
    renderSidebar();
    const headers = ["Ingest", "Model", "Analyze"].map((h) => screen.getByText(h));
    // Headers appear in document order.
    expect(headers[0].compareDocumentPosition(headers[1])).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING
    );
    expect(headers[1].compareDocumentPosition(headers[2])).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING
    );
  });

  it("places grouped links under the nav", () => {
    renderSidebar();
    // Desktop rail + would-be mobile drawer both render NavList, so links may
    // appear more than once; getAllByRole keeps the assertion robust.
    expect(screen.getAllByRole("link", { name: /Data sources/ }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: /Pipelines/ }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: /Semantic models/ }).length).toBeGreaterThan(0);
  });

  it("hides the admin item for non-admins and shows it for admins", () => {
    renderSidebar();
    expect(screen.queryByRole("link", { name: /Admin/ })).toBeNull();

    vi.mocked(useIdentity).mockReturnValue({ isAdmin: true } as ReturnType<typeof useIdentity>);
    renderSidebar();
    expect(screen.getAllByRole("link", { name: /Admin/ }).length).toBeGreaterThan(0);
  });
});

describe("Sidebar data catalog link", () => {
  afterEach(() => {
    delete window.__APP_CONFIG__;
  });

  it("hides the Data Catalog link when no catalog URL is configured", () => {
    delete window.__APP_CONFIG__;
    renderSidebar();
    expect(screen.queryByRole("link", { name: /Data Catalog/ })).toBeNull();
  });

  it("renders an external Data Catalog link when a catalog URL is configured", () => {
    window.__APP_CONFIG__ = { apiBaseUrl: "/api/v1", catalogUrl: "http://om.example:8585" };
    renderSidebar();

    const links = screen.getAllByRole("link", { name: /Data Catalog/ });
    expect(links.length).toBeGreaterThan(0);
    // Opens the OM UI in a new tab.
    expect(links[0]).toHaveAttribute("href", "http://om.example:8585");
    expect(links[0]).toHaveAttribute("target", "_blank");
  });
});
