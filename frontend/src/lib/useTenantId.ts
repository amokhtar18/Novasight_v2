/**
 * useTenantId — the server-resolved tenant id (from /me), used to partition
 * client-side dashboards. Falls back to the token's tenant claim while /me is
 * loading so the UI is usable immediately. Returns null only if neither is known.
 */

import { useMe } from "@/api/hooks";
import { useIdentity } from "@/lib/identity";

export function useTenantId(): string | null {
  const { data } = useMe();
  const { tenant } = useIdentity();
  return data?.tenant_id ?? tenant ?? null;
}
