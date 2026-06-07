/**
 * App root — defines the portal's routes inside the persistent AppShell.
 *
 * Pages are lazy-loaded so each route is its own chunk: the heavy chart code
 * (ECharts) only loads when a charting route is visited, keeping first paint
 * (the Overview) lean. Unknown paths fall back to NotFound.
 */

import { lazy } from "react";
import { Link, Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";

import { AppShell } from "@/components/layout/AppShell";
import { useAuthStore } from "@/store/authStore";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";

const Login = lazy(() =>
  import("@/pages/Login").then((m) => ({ default: m.Login }))
);
const Overview = lazy(() =>
  import("@/pages/Overview").then((m) => ({ default: m.Overview }))
);
const DataSources = lazy(() =>
  import("@/pages/DataSources").then((m) => ({ default: m.DataSources }))
);
const DatasetDetail = lazy(() =>
  import("@/pages/DatasetDetail").then((m) => ({ default: m.DatasetDetail }))
);
const SemanticModels = lazy(() =>
  import("@/pages/SemanticModels").then((m) => ({ default: m.SemanticModels }))
);
const Pipelines = lazy(() =>
  import("@/pages/Pipelines").then((m) => ({ default: m.Pipelines }))
);
const DbtModels = lazy(() =>
  import("@/pages/DbtModels").then((m) => ({ default: m.DbtModels }))
);
const Explore = lazy(() =>
  import("@/pages/Explore").then((m) => ({ default: m.Explore }))
);
const Builder = lazy(() =>
  import("@/pages/Builder").then((m) => ({ default: m.Builder }))
);
const Dashboards = lazy(() =>
  import("@/pages/Dashboards").then((m) => ({ default: m.Dashboards }))
);
const DashboardDetail = lazy(() =>
  import("@/pages/DashboardDetail").then((m) => ({ default: m.DashboardDetail }))
);
const Insights = lazy(() =>
  import("@/pages/Insights").then((m) => ({ default: m.Insights }))
);
const Admin = lazy(() => import("@/pages/Admin").then((m) => ({ default: m.Admin })));
const Settings = lazy(() =>
  import("@/pages/Settings").then((m) => ({ default: m.Settings }))
);

/** Gate: redirect unauthenticated visitors to /login, preserving their target. */
function RequireAuth() {
  const authed = useAuthStore((s) => s.accessToken !== null);
  const location = useLocation();
  if (!authed) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }
  return <Outlet />;
}

function NotFound() {
  return (
    <div className="animate-in-up py-16">
      <EmptyState
        title="Page not found"
        description="The page you're looking for doesn't exist."
        action={
          <Button asChild>
            <Link to="/">Back to overview</Link>
          </Button>
        }
      />
    </div>
  );
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<RequireAuth />}>
        <Route element={<AppShell />}>
          <Route index element={<Overview />} />
          <Route path="data" element={<DataSources />} />
          <Route path="data/:datasetId" element={<DatasetDetail />} />
          <Route path="pipelines" element={<Pipelines />} />
          <Route path="transforms" element={<DbtModels />} />
          <Route path="models" element={<SemanticModels />} />
          <Route path="explore" element={<Explore />} />
          <Route path="build" element={<Builder />} />
          <Route path="dashboards" element={<Dashboards />} />
          <Route path="dashboards/:dashboardId" element={<DashboardDetail />} />
          <Route path="insights" element={<Insights />} />
          <Route path="admin" element={<Admin />} />
          <Route path="settings" element={<Settings />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Route>
    </Routes>
  );
}
