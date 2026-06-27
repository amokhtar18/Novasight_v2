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
const DatasetDetail = lazy(() =>
  import("@/pages/DatasetDetail").then((m) => ({ default: m.DatasetDetail }))
);
const SemanticModels = lazy(() =>
  import("@/pages/SemanticModels").then((m) => ({ default: m.SemanticModels }))
);
const Pipelines = lazy(() =>
  import("@/pages/Pipelines").then((m) => ({ default: m.Pipelines }))
);
const Operations = lazy(() =>
  import("@/pages/Operations").then((m) => ({ default: m.Operations }))
);
const DbtModels = lazy(() =>
  import("@/pages/DbtModels").then((m) => ({ default: m.DbtModels }))
);
const Assistant = lazy(() =>
  import("@/pages/Assistant").then((m) => ({ default: m.Assistant }))
);
const Builder = lazy(() =>
  import("@/pages/Builder").then((m) => ({ default: m.Builder }))
);
const Charts = lazy(() =>
  import("@/pages/Charts").then((m) => ({ default: m.Charts }))
);
const Dashboards = lazy(() =>
  import("@/pages/Dashboards").then((m) => ({ default: m.Dashboards }))
);
const DashboardDetail = lazy(() =>
  import("@/pages/DashboardDetail").then((m) => ({ default: m.DashboardDetail }))
);
const Admin = lazy(() => import("@/pages/Admin").then((m) => ({ default: m.Admin })));
const Settings = lazy(() =>
  import("@/pages/Settings").then((m) => ({ default: m.Settings }))
);

// Dev-only component gallery. import.meta.env.DEV is statically false in prod
// builds, so this branch (and its dynamic import) is tree-shaken out entirely.
const ComponentsGallery = import.meta.env.DEV
  ? lazy(() =>
      import("@/pages/dev/ComponentsGallery").then((m) => ({
        default: m.ComponentsGallery,
      }))
    )
  : null;

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
          {/* The standalone Data sources page is retired into the Ingest hub (#1). */}
          <Route path="data" element={<Navigate to="/pipelines?tab=sources" replace />} />
          <Route path="data/:datasetId" element={<DatasetDetail />} />
          <Route path="pipelines" element={<Pipelines />} />
          <Route path="operations" element={<Operations />} />
          <Route path="transforms" element={<DbtModels />} />
          <Route path="models" element={<SemanticModels />} />
          {/* Ask AI / Chat / Insights are unified into the Assistant (#7/#11). */}
          <Route path="assistant" element={<Assistant />} />
          <Route path="explore" element={<Navigate to="/assistant" replace />} />
          <Route path="chat" element={<Navigate to="/assistant" replace />} />
          <Route path="insights" element={<Navigate to="/assistant" replace />} />
          <Route path="build" element={<Builder />} />
          <Route path="charts" element={<Charts />} />
          <Route path="dashboards" element={<Dashboards />} />
          <Route path="dashboards/:dashboardId" element={<DashboardDetail />} />
          <Route path="admin" element={<Admin />} />
          <Route path="settings" element={<Settings />} />
          {import.meta.env.DEV && ComponentsGallery && (
            <Route path="dev/components" element={<ComponentsGallery />} />
          )}
          <Route path="*" element={<NotFound />} />
        </Route>
      </Route>
    </Routes>
  );
}
