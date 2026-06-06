/**
 * useIdentity — the signed-in user, read from the auth store (populated by login
 * from the server-verified /auth/login response). Drives shell labels and which
 * admin/superuser UI is *shown*. Authorization is always enforced by the backend;
 * this only affects the UI.
 *
 * The role names below are the backend's conventional defaults
 * (`AUTH__PLATFORM_ADMIN_ROLE` / `AUTH__TENANT_SUPERUSER_ROLE`). They gate
 * visibility only — the API rejects unauthorized calls regardless.
 */

import { useAuthStore } from "@/store/authStore";

const PLATFORM_ADMIN_ROLE = "platform_admin";
const TENANT_SUPERUSER_ROLE = "superuser";

export interface Identity {
  /** Tenant slug (display + scoping for client-side stores). */
  tenant: string | null;
  /** Friendly label for the account menu (name → email → tenant). */
  label: string;
  roles: string[];
  isAuthenticated: boolean;
  isPlatformAdmin: boolean;
  isSuperuser: boolean;
  /** Heuristic for showing admin-only nav (platform admin or tenant superuser). */
  isAdmin: boolean;
}

export function useIdentity(): Identity {
  const user = useAuthStore((s) => s.user);
  const token = useAuthStore((s) => s.accessToken);

  const roles = user?.roles ?? [];
  const isPlatformAdmin = roles.includes(PLATFORM_ADMIN_ROLE);
  const isSuperuser = roles.includes(TENANT_SUPERUSER_ROLE);
  return {
    tenant: user?.tenant ?? null,
    label: user?.name ?? user?.email ?? user?.tenant ?? "Signed in",
    roles,
    isAuthenticated: token !== null,
    isPlatformAdmin,
    isSuperuser,
    isAdmin: isPlatformAdmin || isSuperuser,
  };
}
