import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // Load env so VITE_API_PROXY_TARGET is available at config time.
  const env = loadEnv(mode, process.cwd(), "VITE_");

  // The proxy target defaults to http://localhost:8000 for convenience but must
  // be overridden via VITE_API_PROXY_TARGET in production/CI.
  const apiProxyTarget = env.VITE_API_PROXY_TARGET ?? "http://localhost:8000";

  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
    },
    server: {
      proxy: {
        // Proxy /api to the backend so the SPA and API share an origin in dev.
        // This avoids CORS issues without changing the backend.
        "/api": {
          target: apiProxyTarget,
          changeOrigin: true,
        },
      },
    },
  };
});
