/**
 * Settings — appearance (theme) and the resolved tenant context (from /me), plus
 * a small about/brand panel. Read-only platform info; no secrets are shown.
 */

import { Monitor, Moon, Sun } from "lucide-react";

import { useMe } from "@/api/hooks";
import { useTheme, type Theme } from "@/lib/theme";
import { PageHeader } from "@/components/layout/PageHeader";
import { BrandMark } from "@/components/BrandMark";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/cn";

const THEMES: { value: Theme; label: string; icon: typeof Sun }[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
];

export function Settings() {
  const { theme, setTheme } = useTheme();
  const { data: me, isLoading } = useMe();

  const contextRows: { label: string; value: string | undefined }[] = [
    { label: "Tenant", value: me?.tenant_id },
    { label: "Iceberg namespace", value: me?.iceberg_namespace },
    { label: "ClickHouse database", value: me?.clickhouse_db },
    { label: "dbt schema", value: me?.dbt_schema },
  ];

  return (
    <div className="animate-in-up max-w-3xl">
      <PageHeader title="Settings" description="Appearance and workspace details." />

      {/* Appearance */}
      <Card className="mb-6 bg-card/70">
        <CardHeader>
          <CardTitle className="text-base">Appearance</CardTitle>
          <CardDescription>Choose your theme. The app defaults to dark.</CardDescription>
        </CardHeader>
        <CardContent>
          <div role="radiogroup" aria-label="Theme" className="grid grid-cols-3 gap-3">
            {THEMES.map((t) => {
              const active = theme === t.value;
              return (
                <button
                  key={t.value}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  onClick={() => setTheme(t.value)}
                  className={cn(
                    "flex flex-col items-center gap-2 rounded-xl border p-4 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    active
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border text-muted-foreground hover:border-primary/50 hover:text-foreground"
                  )}
                >
                  <t.icon className="h-5 w-5" aria-hidden />
                  {t.label}
                </button>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* Tenant context */}
      <Card className="mb-6 bg-card/70">
        <CardHeader>
          <CardTitle className="text-base">Workspace</CardTitle>
          <CardDescription>
            Your tenant's resolved context, derived server-side from your token.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="divide-y divide-border/60">
            {contextRows.map((row) => (
              <div key={row.label} className="flex items-center justify-between gap-4 py-2.5">
                <dt className="text-sm text-muted-foreground">{row.label}</dt>
                <dd className="truncate text-sm font-medium">
                  {isLoading ? <Skeleton className="h-4 w-32" /> : (row.value ?? "—")}
                </dd>
              </div>
            ))}
          </dl>
        </CardContent>
      </Card>

      {/* About */}
      <Card className="bg-card/70">
        <CardContent className="flex items-center gap-4 pt-6">
          <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10 ring-1 ring-inset ring-primary/20">
            <BrandMark className="h-7 w-7" />
          </span>
          <div>
            <p className="font-semibold tracking-tight text-gradient">NovaSight</p>
            <p className="text-sm text-muted-foreground">
              Managed, low-code data analytics & BI — one codebase, on-prem to cloud.
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
