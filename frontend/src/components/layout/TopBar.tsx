/**
 * TopBar — sticky header with the page title, tenant badge, theme toggle, and
 * the account menu. Hosts the mobile nav trigger and the desktop collapse toggle.
 */

import { Link, useLocation } from "react-router-dom";
import {
  LogOut,
  Menu,
  Monitor,
  Moon,
  PanelLeft,
  Settings as SettingsIcon,
  Sun,
} from "lucide-react";

import { useUiStore } from "@/store/uiStore";
import { useTheme, type Theme } from "@/lib/theme";
import { useIdentity } from "@/lib/identity";
import { useLogout } from "@/api/hooks";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownItem,
  DropdownLabel,
  DropdownSeparator,
} from "@/components/ui/dropdown-menu";
import { titleForPath } from "./nav";

const THEME_OPTIONS: { value: Theme; label: string; icon: typeof Sun }[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
];

export function TopBar() {
  const { pathname } = useLocation();
  const toggleSidebar = useUiStore((s) => s.toggleSidebar);
  const setMobileNav = useUiStore((s) => s.setMobileNav);
  const { theme, resolvedTheme, setTheme, toggle } = useTheme();
  const { tenant, label, isAdmin } = useIdentity();
  const logout = useLogout();

  return (
    <header className="sticky top-0 z-[var(--z-sticky)] flex h-14 items-center gap-2 border-b border-border/60 bg-background/70 px-3 backdrop-blur md:px-5">
      {/* Mobile nav trigger */}
      <button
        type="button"
        onClick={() => setMobileNav(true)}
        aria-label="Open navigation"
        className="rounded-md p-2 text-muted-foreground hover:bg-accent hover:text-foreground md:hidden"
      >
        <Menu className="h-5 w-5" />
      </button>

      {/* Desktop collapse toggle */}
      <button
        type="button"
        onClick={toggleSidebar}
        aria-label="Toggle sidebar"
        className="hidden rounded-md p-2 text-muted-foreground hover:bg-accent hover:text-foreground md:inline-flex"
      >
        <PanelLeft className="h-5 w-5" />
      </button>

      <h1 className="truncate text-sm font-semibold tracking-tight">
        {titleForPath(pathname)}
      </h1>

      <div className="ml-auto flex items-center gap-2">
        {tenant && (
          <Badge variant="outline" className="hidden sm:inline-flex">
            <span className="h-1.5 w-1.5 rounded-full bg-success" aria-hidden />
            {tenant}
          </Badge>
        )}

        {/* Quick theme toggle */}
        <button
          type="button"
          onClick={toggle}
          aria-label="Toggle theme"
          className="rounded-md p-2 text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {resolvedTheme === "dark" ? (
            <Moon className="h-[18px] w-[18px]" />
          ) : (
            <Sun className="h-[18px] w-[18px]" />
          )}
        </button>

        {/* Account menu */}
        <DropdownMenu
          label="Account menu"
          trigger={
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/15 text-xs font-semibold text-primary ring-1 ring-inset ring-primary/25">
              {label.slice(0, 2).toUpperCase()}
            </span>
          }
        >
          <DropdownLabel>{label}</DropdownLabel>
          {tenant && (
            <DropdownLabel className="pt-0 font-normal">
              Tenant: <span className="text-foreground">{tenant}</span>
              {isAdmin && (
                <Badge variant="info" className="ml-2">
                  admin
                </Badge>
              )}
            </DropdownLabel>
          )}
          <DropdownSeparator />
          <DropdownLabel className="font-normal">Theme</DropdownLabel>
          {THEME_OPTIONS.map((opt) => (
            <DropdownItem
              key={opt.value}
              onClick={() => setTheme(opt.value)}
              className={theme === opt.value ? "text-primary" : undefined}
            >
              <opt.icon className="h-4 w-4" aria-hidden />
              {opt.label}
            </DropdownItem>
          ))}
          <DropdownSeparator />
          <Link
            to="/settings"
            role="menuitem"
            className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-sm transition-colors hover:bg-accent hover:text-accent-foreground"
          >
            <SettingsIcon className="h-4 w-4" aria-hidden />
            Settings
          </Link>
          <DropdownSeparator />
          <DropdownItem onClick={() => logout.mutate()}>
            <LogOut className="h-4 w-4" aria-hidden />
            Sign out
          </DropdownItem>
        </DropdownMenu>
      </div>
    </header>
  );
}
