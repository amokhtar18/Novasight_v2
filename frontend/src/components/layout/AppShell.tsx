/**
 * AppShell — the persistent application chrome: sidebar + topbar + scrollable
 * content area where routed pages render via <Outlet>. Also mounts the global
 * toaster and a skip-to-content link for keyboard users.
 */

import { Suspense } from "react";
import { Outlet } from "react-router-dom";
import { Toaster } from "sonner";

import { useTheme } from "@/lib/theme";
import { Spinner } from "@/components/ui/spinner";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

export function AppShell() {
  const { resolvedTheme } = useTheme();
  return (
    <div className="flex min-h-screen">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-[var(--z-overlay)] focus:rounded-md focus:bg-primary focus:px-3 focus:py-2 focus:text-primary-foreground"
      >
        Skip to content
      </a>
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main
          id="main-content"
          className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 md:px-6 lg:px-8"
        >
          <Suspense
            fallback={
              <div className="flex h-64 items-center justify-center">
                <Spinner label="Loading page" />
              </div>
            }
          >
            <Outlet />
          </Suspense>
        </main>
      </div>
      <Toaster
        position="bottom-right"
        theme={resolvedTheme}
        richColors
        closeButton
      />
    </div>
  );
}
