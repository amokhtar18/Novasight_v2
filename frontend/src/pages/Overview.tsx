/**
 * Overview — the portal home. Greets the user, shows live system health and a
 * few key counts, surfaces quick actions, and lists recent datasets + saved
 * dashboards so users land somewhere useful.
 */

import { Link } from "react-router-dom";
import {
  ArrowRight,
  BarChart3,
  Database,
  LayoutDashboard,
  Lightbulb,
  Sparkles,
  Upload,
} from "lucide-react";

import { useDashboards, useDatasets, useHealth } from "@/api/hooks";
import { useIdentity } from "@/lib/identity";
import { PageHeader } from "@/components/layout/PageHeader";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { formatRelativeTime } from "@/lib/format";

const QUICK_ACTIONS = [
  {
    to: "/explore",
    icon: Sparkles,
    title: "Ask a question",
    desc: "Query your data in plain English.",
  },
  {
    to: "/data",
    icon: Upload,
    title: "Upload data",
    desc: "Add a CSV to start analysing.",
  },
  {
    to: "/build",
    icon: BarChart3,
    title: "Build a chart",
    desc: "Point-and-click chart builder.",
  },
  {
    to: "/insights",
    icon: Lightbulb,
    title: "Get insights",
    desc: "AI summaries of your metrics.",
  },
];

export function Overview() {
  const { label } = useIdentity();
  const { data: datasets, isLoading: datasetsLoading } = useDatasets();
  const { data: health, isLoading: healthLoading } = useHealth();
  const { data: dashboards = [] } = useDashboards();

  const recentDatasets = (datasets ?? []).slice(0, 5);

  return (
    <div className="animate-in-up">
      <PageHeader
        title={
          <>
            Welcome back<span className="text-muted-foreground">,</span>{" "}
            <span className="text-gradient">{label.split("@")[0]}</span>
          </>
        }
        description="Your analytics workspace — connect data, ask questions, and build dashboards without touching infrastructure."
      />

      {/* Stat row */}
      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          icon={Database}
          label="Datasets"
          value={datasetsLoading ? undefined : (datasets?.length ?? 0)}
          to="/data"
        />
        <StatCard
          icon={LayoutDashboard}
          label="Dashboards"
          value={dashboards.length}
          to="/dashboards"
        />
        <Card className="col-span-2 bg-card/70">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              System health
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap items-center gap-2">
            {healthLoading ? (
              <Skeleton className="h-6 w-40" />
            ) : health ? (
              <>
                <Badge variant={health.status === "healthy" ? "success" : "warning"}>
                  {health.status}
                </Badge>
                {health.components.map((c) => (
                  <Badge
                    key={c.name}
                    variant={c.status === "up" ? "outline" : "danger"}
                  >
                    <span
                      className={`h-1.5 w-1.5 rounded-full ${
                        c.status === "up" ? "bg-success" : "bg-destructive"
                      }`}
                      aria-hidden
                    />
                    {c.name}
                  </Badge>
                ))}
              </>
            ) : (
              <Badge variant="danger">unreachable</Badge>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Quick actions */}
      <h3 className="mb-3 text-sm font-medium text-muted-foreground">Quick actions</h3>
      <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {QUICK_ACTIONS.map((a) => (
          <Link
            key={a.to}
            to={a.to}
            className="group rounded-xl border bg-card/70 p-5 transition-colors hover:border-primary/50 hover:bg-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <span className="mb-3 flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary ring-1 ring-inset ring-primary/20">
              <a.icon className="h-5 w-5" aria-hidden />
            </span>
            <p className="flex items-center gap-1 font-medium">
              {a.title}
              <ArrowRight className="h-4 w-4 opacity-0 transition-opacity group-hover:opacity-100" aria-hidden />
            </p>
            <p className="mt-1 text-sm text-muted-foreground">{a.desc}</p>
          </Link>
        ))}
      </div>

      {/* Recent datasets + dashboards */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card className="bg-card/70">
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle className="text-base">Recent datasets</CardTitle>
            <Link to="/data" className="text-sm text-primary hover:underline">
              View all
            </Link>
          </CardHeader>
          <CardContent>
            {datasetsLoading ? (
              <div className="space-y-2">
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
              </div>
            ) : recentDatasets.length ? (
              <ul className="divide-y divide-border/60">
                {recentDatasets.map((d) => (
                  <li key={d.id}>
                    <Link
                      to={`/data/${d.id}`}
                      className="flex items-center justify-between gap-3 py-2.5 transition-colors hover:text-primary"
                    >
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-medium">{d.name}</span>
                        <span className="block truncate text-xs text-muted-foreground">
                          {formatRelativeTime(d.created_at)}
                        </span>
                      </span>
                      <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState
                icon={<Database className="h-6 w-6" />}
                title="No datasets yet"
                description="Upload a CSV to get started."
              />
            )}
          </CardContent>
        </Card>

        <Card className="bg-card/70">
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle className="text-base">Your dashboards</CardTitle>
            <Link to="/dashboards" className="text-sm text-primary hover:underline">
              View all
            </Link>
          </CardHeader>
          <CardContent>
            {dashboards.length ? (
              <ul className="divide-y divide-border/60">
                {dashboards.slice(0, 5).map((b) => (
                  <li key={b.id}>
                    <Link
                      to={`/dashboards/${b.id}`}
                      className="flex items-center justify-between gap-3 py-2.5 transition-colors hover:text-primary"
                    >
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-medium">{b.name}</span>
                        <span className="block truncate text-xs text-muted-foreground">
                          {b.tile_count} chart{b.tile_count === 1 ? "" : "s"}
                        </span>
                      </span>
                      <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState
                icon={<LayoutDashboard className="h-6 w-6" />}
                title="No dashboards yet"
                description="Build a chart and pin it to a new dashboard."
              />
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
  to,
}: {
  icon: typeof Database;
  label: string;
  value: number | undefined;
  to: string;
}) {
  return (
    <Link
      to={to}
      className="rounded-xl border bg-card/70 p-5 transition-colors hover:border-primary/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <span className="mb-3 flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
        <Icon className="h-[18px] w-[18px]" aria-hidden />
      </span>
      {value === undefined ? (
        <Skeleton className="h-8 w-12" />
      ) : (
        <p className="text-3xl font-semibold tracking-tight tabular-nums">{value}</p>
      )}
      <p className="text-sm text-muted-foreground">{label}</p>
    </Link>
  );
}
