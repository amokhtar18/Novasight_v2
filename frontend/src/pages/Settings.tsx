/**
 * Settings — appearance (theme) and the resolved tenant context (from /me), plus
 * a small about/brand panel. Read-only platform info; no secrets are shown.
 */

import { Monitor, Moon, Sparkles, Sun } from "lucide-react";

import { useAiHealth, useMe } from "@/api/hooks";
import { useIdentity } from "@/lib/identity";
import { useTheme, type Theme } from "@/lib/theme";
import { PageHeader } from "@/components/layout/PageHeader";
import { BrandMark } from "@/components/BrandMark";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
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

      {/* AI provider connectivity */}
      <AiProviderCard />

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

/**
 * AiProviderCard — verify the configured AI provider + key with a live probe (#12).
 *
 * Superuser-only (the probe spends a few tokens); other users see a muted note. The
 * probe never reveals the key — only a connected/failed status, the answering model,
 * and round-trip latency.
 */
function AiProviderCard() {
  const { isSuperuser } = useIdentity();
  const probe = useAiHealth();
  const result = probe.data;

  return (
    <Card className="mb-6 bg-card/70">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Sparkles className="h-4 w-4 text-primary" aria-hidden />
          AI provider
        </CardTitle>
        <CardDescription>
          Check that the configured model and API key are working. The key is never shown.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {isSuperuser ? (
          <>
            <div className="flex flex-wrap items-center gap-3">
              <Button size="sm" onClick={() => probe.mutate()} disabled={probe.isPending}>
                {probe.isPending ? (
                  <Spinner className="text-primary-foreground" />
                ) : (
                  <Sparkles className="h-4 w-4" aria-hidden />
                )}
                Test connection
              </Button>
              {result?.ok && <Badge variant="success">Connected</Badge>}
              {result && !result.ok && <Badge variant="danger">Failed</Badge>}
              {probe.isError && <Badge variant="danger">Error</Badge>}
            </div>
            {result?.ok && (
              <p className="text-sm text-muted-foreground">
                Responded as{" "}
                <span className="font-medium text-foreground">{result.model}</span>
                {result.latency_ms != null ? ` in ${result.latency_ms} ms.` : "."}
              </p>
            )}
            {result && !result.ok && result.detail && (
              <p className="text-sm text-destructive">{result.detail}</p>
            )}
            {probe.isError && (
              <p className="text-sm text-destructive">
                {probe.error instanceof Error
                  ? probe.error.message
                  : "Could not reach the server to run the test."}
              </p>
            )}
          </>
        ) : (
          <p className="text-sm text-muted-foreground">
            Only workspace admins can run the AI connection test.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
