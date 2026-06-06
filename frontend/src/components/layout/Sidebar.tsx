/**
 * Sidebar — primary navigation rail.
 *
 * Desktop: a fixed rail that collapses to icons (uiStore.sidebarCollapsed).
 * Mobile: a slide-over drawer (uiStore.mobileNavOpen) with a backdrop.
 * The brand mark links home; nav uses NavLink so the active route is styled.
 */

import { NavLink } from "react-router-dom";
import { X } from "lucide-react";

import { cn } from "@/lib/cn";
import { useUiStore } from "@/store/uiStore";
import { useIdentity } from "@/lib/identity";
import { BrandMark } from "@/components/BrandMark";
import { FOOTER_ITEMS, NAV_ITEMS, type NavItem } from "./nav";

function NavList({
  collapsed,
  onNavigate,
}: {
  collapsed: boolean;
  onNavigate?: () => void;
}) {
  const { isAdmin } = useIdentity();
  const items = NAV_ITEMS.filter((i) => !i.adminOnly || isAdmin);

  const renderItem = (item: NavItem) => (
    <NavLink
      key={item.to}
      to={item.to}
      end={item.end}
      onClick={onNavigate}
      title={collapsed ? item.label : undefined}
      className={({ isActive }) =>
        cn(
          "group flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
          collapsed && "justify-center px-0",
          isActive
            ? "bg-primary/15 text-primary"
            : "text-muted-foreground hover:bg-accent/60 hover:text-foreground"
        )
      }
    >
      {({ isActive }) => (
        <>
          <item.icon
            className={cn(
              "h-[18px] w-[18px] shrink-0",
              isActive ? "text-primary" : "text-muted-foreground group-hover:text-foreground"
            )}
            aria-hidden
          />
          {!collapsed && <span className="truncate">{item.label}</span>}
        </>
      )}
    </NavLink>
  );

  return (
    <nav className="flex flex-1 flex-col gap-1" aria-label="Primary">
      {items.map(renderItem)}
      <div className="mt-auto flex flex-col gap-1 pt-2">
        {FOOTER_ITEMS.map(renderItem)}
      </div>
    </nav>
  );
}

function Brand({ collapsed }: { collapsed: boolean }) {
  return (
    <NavLink
      to="/"
      className="flex items-center gap-2.5 rounded-lg px-1 py-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      aria-label="NovaSight home"
    >
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 ring-1 ring-inset ring-primary/20">
        <BrandMark className="h-5 w-5" />
      </span>
      {!collapsed && (
        <span className="text-base font-semibold tracking-tight text-gradient">
          NovaSight
        </span>
      )}
    </NavLink>
  );
}

export function Sidebar() {
  const collapsed = useUiStore((s) => s.sidebarCollapsed);
  const mobileOpen = useUiStore((s) => s.mobileNavOpen);
  const setMobileNav = useUiStore((s) => s.setMobileNav);

  return (
    <>
      {/* Desktop rail */}
      <aside
        className={cn(
          "sticky top-0 hidden h-screen shrink-0 flex-col gap-4 border-r border-border/60 bg-card/40 p-3 transition-[width] duration-200 md:flex",
          collapsed ? "w-[68px]" : "w-60"
        )}
      >
        <Brand collapsed={collapsed} />
        <NavList collapsed={collapsed} />
      </aside>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 md:hidden">
          <div
            className="absolute inset-0 bg-background/70 backdrop-blur-sm"
            onClick={() => setMobileNav(false)}
            aria-hidden
          />
          <aside className="absolute left-0 top-0 flex h-full w-64 flex-col gap-4 border-r bg-card p-3 shadow-2xl animate-in-up">
            <div className="flex items-center justify-between">
              <Brand collapsed={false} />
              <button
                type="button"
                onClick={() => setMobileNav(false)}
                aria-label="Close navigation"
                className="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <NavList collapsed={false} onNavigate={() => setMobileNav(false)} />
          </aside>
        </div>
      )}
    </>
  );
}
