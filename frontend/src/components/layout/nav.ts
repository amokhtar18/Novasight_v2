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
  Settings,
  Shield,
  Sparkles,
  Workflow,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** Match the route exactly (used for the index "/" route). */
  end?: boolean;
  /** Only render when the caller is a platform admin. */
  adminOnly?: boolean;
}

/** Primary navigation, in display order. */
export const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Overview", icon: LayoutGrid, end: true },
  { to: "/data", label: "Data sources", icon: Database },
  { to: "/pipelines", label: "Pipelines", icon: Workflow },
  { to: "/operations", label: "Operations", icon: Activity },
  { to: "/transforms", label: "Transforms", icon: Boxes },
  { to: "/models", label: "Semantic models", icon: Layers },
  { to: "/explore", label: "Ask AI", icon: Sparkles },
  { to: "/chat", label: "Chat", icon: MessageSquare },
  { to: "/build", label: "Chart builder", icon: BarChart3 },
  { to: "/dashboards", label: "Dashboards", icon: LayoutDashboard },
  { to: "/insights", label: "Insights", icon: Lightbulb },
  { to: "/admin", label: "Admin", icon: Shield, adminOnly: true },
];

/** Secondary navigation pinned to the sidebar footer. */
export const FOOTER_ITEMS: NavItem[] = [
  { to: "/settings", label: "Settings", icon: Settings },
];

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
