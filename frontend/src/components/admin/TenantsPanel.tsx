/**
 * TenantsPanel — read-only list of all tenants (platform admin).
 *
 * Provisioning/de-provisioning live in their own cards on the Admin page; this
 * panel is the at-a-glance roster with each tenant's physical coordinates.
 */

import { Building2 } from "lucide-react";

import { useTenants } from "@/api/hooks";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

export function TenantsPanel() {
  const { data: tenants, isLoading, isError } = useTenants();

  return (
    <Card className="bg-card/70">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Building2 className="h-4 w-4 text-primary" aria-hidden />
          Tenants
        </CardTitle>
        <CardDescription>All workspaces and their isolated resources.</CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : isError ? (
          <Alert variant="destructive">
            <AlertTitle>Couldn't load tenants</AlertTitle>
            <AlertDescription>Platform-admin role is required.</AlertDescription>
          </Alert>
        ) : (
          <div className="overflow-hidden rounded-lg border">
            <table className="w-full text-sm">
              <thead className="bg-muted/60 text-left text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 font-medium">Slug</th>
                  <th className="px-3 py-2 font-medium">Name</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 font-medium">ClickHouse DB</th>
                </tr>
              </thead>
              <tbody>
                {(tenants ?? []).map((t) => (
                  <tr key={t.id} className="border-t border-border/60">
                    <td className="px-3 py-2 font-medium">{t.slug}</td>
                    <td className="px-3 py-2">{t.name}</td>
                    <td className="px-3 py-2">
                      <Badge variant={t.status === "active" ? "success" : "warning"}>
                        {t.status}
                      </Badge>
                    </td>
                    <td className="px-3 py-2 text-muted-foreground">{t.clickhouse_db}</td>
                  </tr>
                ))}
                {(tenants ?? []).length === 0 && (
                  <tr>
                    <td colSpan={4} className="px-3 py-6 text-center text-muted-foreground">
                      No tenants found.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
