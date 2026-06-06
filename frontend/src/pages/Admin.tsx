/**
 * Admin — the control plane, surfaced in-app so operators never need Grafana,
 * the ClickHouse client, or a shell to run day-to-day tasks:
 *   - live system health (Postgres, Redis, …);
 *   - provision a new isolated tenant;
 *   - de-provision a tenant (guarded by a typed confirmation).
 *
 * Every action is authorized server-side (platform-admin role). This page is
 * only *shown* to admin-looking tokens; the backend remains the gate.
 */

import { useState } from "react";
import { Activity, ServerCog, ShieldAlert, Trash2 } from "lucide-react";
import { toast } from "sonner";

import {
  useDeprovisionTenant,
  useHealth,
  useProvisionTenant,
} from "@/api/hooks";
import { useIdentity } from "@/lib/identity";
import { UsersPanel } from "@/components/admin/UsersPanel";
import { TenantsPanel } from "@/components/admin/TenantsPanel";
import { PageHeader } from "@/components/layout/PageHeader";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  Dialog,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

export function Admin() {
  const { isPlatformAdmin } = useIdentity();
  const { data: health, isLoading: healthLoading } = useHealth();
  const provision = useProvisionTenant();
  const deprovision = useDeprovisionTenant();

  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [deleteSlug, setDeleteSlug] = useState("");
  const [confirmText, setConfirmText] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);

  function handleProvision(e: React.FormEvent) {
    e.preventDefault();
    provision.mutate(
      { slug: slug.trim(), name: name.trim(), admin_email: adminEmail.trim() },
      {
        onSuccess: (t) => {
          toast.success(`Tenant “${t.name}” provisioned`);
          setSlug("");
          setName("");
          setAdminEmail("");
        },
        onError: (err) =>
          toast.error(err instanceof Error ? err.message : "Provisioning failed"),
      }
    );
  }

  function handleDeprovision() {
    deprovision.mutate(deleteSlug.trim(), {
      onSuccess: () => {
        toast.success(`Tenant “${deleteSlug}” de-provisioned`);
        setDeleteSlug("");
        setConfirmText("");
        setConfirmOpen(false);
      },
      onError: (err) => {
        toast.error(err instanceof Error ? err.message : "De-provisioning failed");
        setConfirmOpen(false);
      },
    });
  }

  return (
    <div className="animate-in-up">
      <PageHeader
        title="Admin"
        description="Operate the platform without leaving the portal — health, tenant provisioning, and lifecycle."
      />

      <Alert className="mb-6">
        <ShieldAlert className="h-4 w-4" aria-hidden />
        <AlertTitle>Platform admin</AlertTitle>
        <AlertDescription>
          These actions require the platform-admin role and are enforced by the API.
        </AlertDescription>
      </Alert>

      {/* System health */}
      <Card className="mb-6 bg-card/70">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Activity className="h-4 w-4 text-primary" aria-hidden />
            System health
          </CardTitle>
          <CardDescription>Live dependency probes, refreshed automatically.</CardDescription>
        </CardHeader>
        <CardContent>
          {healthLoading ? (
            <Skeleton className="h-20 w-full" />
          ) : health ? (
            <div className="space-y-3">
              <Badge variant={health.status === "healthy" ? "success" : "warning"}>
                {health.status}
              </Badge>
              <div className="overflow-hidden rounded-lg border">
                <table className="w-full text-sm">
                  <thead className="bg-muted/60 text-left text-xs text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2 font-medium">Component</th>
                      <th className="px-3 py-2 font-medium">Status</th>
                      <th className="px-3 py-2 font-medium">Detail</th>
                    </tr>
                  </thead>
                  <tbody>
                    {health.components.map((c) => (
                      <tr key={c.name} className="border-t border-border/60">
                        <td className="px-3 py-2 font-medium">{c.name}</td>
                        <td className="px-3 py-2">
                          <Badge variant={c.status === "up" ? "success" : "danger"}>
                            {c.status}
                          </Badge>
                        </td>
                        <td className="px-3 py-2 text-muted-foreground">{c.detail ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <Alert variant="destructive">
              <AlertTitle>Health unavailable</AlertTitle>
              <AlertDescription>Could not reach the health endpoint.</AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>

      {/* User management (tenant superuser) */}
      <div className="mb-6">
        <UsersPanel />
      </div>

      {/* Tenant roster (platform admin only) */}
      {isPlatformAdmin && (
        <div className="mb-6">
          <TenantsPanel />
        </div>
      )}

      {isPlatformAdmin && (
      <>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Provision */}
        <Card className="bg-card/70">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <ServerCog className="h-4 w-4 text-primary" aria-hidden />
              Provision tenant
            </CardTitle>
            <CardDescription>
              Creates an isolated environment (Iceberg namespace, ClickHouse DB, dbt schema).
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleProvision} className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="t-slug">Slug</Label>
                <Input
                  id="t-slug"
                  value={slug}
                  onChange={(e) => setSlug(e.target.value)}
                  placeholder="acme"
                  required
                  minLength={2}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="t-name">Name</Label>
                <Input
                  id="t-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Acme Corp"
                  required
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="t-email">Admin email</Label>
                <Input
                  id="t-email"
                  type="email"
                  value={adminEmail}
                  onChange={(e) => setAdminEmail(e.target.value)}
                  placeholder="admin@acme.example"
                  required
                />
              </div>
              <Button type="submit" disabled={provision.isPending} className="w-full">
                {provision.isPending ? "Provisioning…" : "Provision"}
              </Button>
            </form>

            {provision.data && (
              <Alert className="mt-4">
                <AlertTitle>Provisioned “{provision.data.name}”</AlertTitle>
                <AlertDescription>
                  <dl className="mt-1 space-y-0.5 text-xs">
                    <div className="flex gap-2">
                      <dt className="text-muted-foreground">Iceberg</dt>
                      <dd>{provision.data.iceberg_namespace}</dd>
                    </div>
                    <div className="flex gap-2">
                      <dt className="text-muted-foreground">ClickHouse</dt>
                      <dd>{provision.data.clickhouse_db}</dd>
                    </div>
                    <div className="flex gap-2">
                      <dt className="text-muted-foreground">dbt schema</dt>
                      <dd>{provision.data.dbt_schema}</dd>
                    </div>
                  </dl>
                </AlertDescription>
              </Alert>
            )}
          </CardContent>
        </Card>

        {/* De-provision */}
        <Card className="border-destructive/30 bg-card/70">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Trash2 className="h-4 w-4 text-destructive" aria-hidden />
              De-provision tenant
            </CardTitle>
            <CardDescription>
              Permanently drops the tenant's resources and registry entry.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="d-slug">Tenant slug</Label>
              <Input
                id="d-slug"
                value={deleteSlug}
                onChange={(e) => setDeleteSlug(e.target.value)}
                placeholder="acme"
              />
            </div>
            <Button
              variant="destructive"
              disabled={!deleteSlug.trim() || deprovision.isPending}
              onClick={() => {
                setConfirmText("");
                setConfirmOpen(true);
              }}
              className="w-full"
            >
              De-provision…
            </Button>
          </CardContent>
        </Card>
      </div>

      {/* Typed-confirm delete */}
      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen} title="Confirm de-provision">
        <DialogHeader>
          <DialogTitle>De-provision “{deleteSlug}”?</DialogTitle>
          <DialogDescription>
            This is irreversible. Type the slug <strong>{deleteSlug}</strong> to confirm.
          </DialogDescription>
        </DialogHeader>
        <Input
          value={confirmText}
          onChange={(e) => setConfirmText(e.target.value)}
          placeholder={deleteSlug}
          aria-label="Type slug to confirm"
          autoFocus
        />
        <DialogFooter>
          <Button variant="ghost" onClick={() => setConfirmOpen(false)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            disabled={confirmText !== deleteSlug || deprovision.isPending}
            onClick={handleDeprovision}
          >
            {deprovision.isPending ? "Working…" : "De-provision"}
          </Button>
        </DialogFooter>
      </Dialog>
      </>
      )}
    </div>
  );
}
