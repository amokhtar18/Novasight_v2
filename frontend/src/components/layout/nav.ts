/**
 * Navigation model for the app shell. Single source of truth for the sidebar
 * links and the topbar page title, so the two never drift.
 */

import {
  Activity,
  BarChart3,
  Boxes,
  Database,
  Layers,
  LayoutDashboard,
  LayoutGrid,
  Lightbulb,
  MessageSquare,
  Network,
  Settings,
  Shield,
  Sparkles,
  Workflow,
  type LucideIcon,
} from "lucide-react";

/**
 * Sidebar sections, in display order. Items carry their group so the rail can
 * render a header before each section (golden source of grouping; the Sidebar
 * never hardcodes the order). ``undefined`` renders at the top with no header.
 */
export type NavGroup = "Ingest" | "Model" | "Analyze" | "Admin";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** Section this item belongs to; undefined renders ungrouped at the top. */
  group?: NavGroup;
  /** Match the route exactly (used for the index "/" route). */
  end?: boolean;
  /** Only render when the caller is a platform admin. */
  adminOnly?: boolean;
}

/** Primary navigation, in display order (grouped by ``group``). */
export const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Overview", icon: LayoutGrid, end: true },
  { to: "/data", label: "Data sources", icon: Database, group: "Ingest" },
  { to: "/pipelines", label: "Pipelines", icon: Workflow, group: "Ingest" },
  { to: "/operations", label: "Operations", icon: Activity, group: "Ingest" },
  { to: "/transforms", label: "Transforms", icon: Boxes, group: "Model" },
  { to: "/models", label: "Semantic models", icon: Layers, group: "Model" },
  { to: "/explore", label: "Ask AI", icon: Sparkles, group: "Analyze" },
  { to: "/chat", label: "Chat", icon: MessageSquare, group: "Analyze" },
  { to: "/build", label: "Chart builder", icon: BarChart3, group: "Analyze" },
  { to: "/dashboards", label: "Dashboards", icon: LayoutDashboard, group: "Analyze" },
  { to: "/insights", label: "Insights", icon: Lightbulb, group: "Analyze" },
  { to: "/admin", label: "Admin", icon: Shield, group: "Admin", adminOnly: true },
];

/** Secondary navigation pinned to the sidebar footer. */
export const FOOTER_ITEMS: NavItem[] = [
  { to: "/settings", label: "Settings", icon: Settings },
];

/** An external link (opens in a new tab) rather than an in-app route. */
export interface ExternalNavItem {
  href: string;
  label: string;
  icon: LucideIcon;
}

/**
 * External links resolved from runtime config. The OpenMetadata catalog is a
 * separate app, so it links out to its own UI; the item only appears when a catalog
 * URL is configured (golden source: ``window.__APP_CONFIG__.catalogUrl``).
 */
export function externalNavItems(catalogUrl?: string): ExternalNavItem[] {
  if (!catalogUrl) return [];
  return [{ href: catalogUrl, label: "Data Catalog", icon: Network }];
}

/** Resolve a human page title from the current pathname (for the topbar). */
export function titleForPath(pathname: string): string {
  if (pathname === "/") return "Overview";
  if (pathname.startsWith("/data")) return "Data sources";
  if (pathname.startsWith("/pipelines")) return "Pipelines";
  if (pathname.startsWith("/operations")) return "Operations";
  if (pathname.startsWith("/transforms")) return "Transforms";
  if (pathname.startsWith("/models")) return "Semantic models";
  if (pathname.startsWith("/explore")) return "Ask AI";
  if (pathname.startsWith("/chat")) return "Chat";
  if (pathname.startsWith("/build")) return "Chart builder";
  if (pathname.startsWith("/dashboards")) return "Dashboards";
  if (pathname.startsWith("/insights")) return "Insights";
  if (pathname.startsWith("/admin")) return "Admin";
  if (pathname.startsWith("/settings")) return "Settings";
  return "NovaSight";
}
