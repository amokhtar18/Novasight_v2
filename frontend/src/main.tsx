/**
 * Application entry point.
 *
 * Bootstraps runtime config (fails loudly if misconfigured), sets up providers,
 * and mounts the app.
 */

import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { loadConfig } from "@/lib/config";
import { ThemeProvider } from "@/lib/theme";
import { App } from "./App";
import "./index.css";
import "gridstack/dist/gridstack.css";

// ---- Runtime config bootstrap -----------------------------------------------
// loadConfig() throws if window.__APP_CONFIG__ is absent or malformed.
// This intentionally crashes before React mounts so the developer sees a clear
// error instead of silent 401s.
loadConfig();

// ---- TanStack Query client --------------------------------------------------
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 30_000,
    },
    mutations: {
      retry: 0,
    },
  },
});

// ---- Mount ------------------------------------------------------------------
const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("#root element not found in the DOM");

createRoot(rootEl).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </ThemeProvider>
    </QueryClientProvider>
  </React.StrictMode>
);
