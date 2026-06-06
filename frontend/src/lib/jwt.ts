/**
 * Display-only JWT decoding.
 *
 * Decodes the (unverified) JWT payload purely to drive presentation — showing
 * the tenant label in the shell and revealing the Admin nav for platform admins.
 * This is NEVER trusted for authorization: the backend independently verifies
 * the signature and enforces every protected route (tenancy + platform-admin
 * role). A tampered token only changes what the local UI *shows*, not what the
 * server *allows*.
 */

export interface JwtClaims {
  /** Subject — usually the user id. */
  sub?: string;
  /** Tenant claim the backend uses to resolve the tenant context. */
  tenant?: string;
  /** Roles claim — may be a list or a space-delimited string, depending on IdP. */
  roles?: string[] | string;
  /** Human-friendly name/email if present. */
  email?: string;
  name?: string;
  [key: string]: unknown;
}

/** Base64url-decode a single JWT segment into JSON, or null if malformed. */
export function decodeJwt(token: string | undefined | null): JwtClaims | null {
  if (!token) return null;
  const parts = token.split(".");
  if (parts.length < 2) return null;
  try {
    const payload = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = payload.padEnd(
      payload.length + ((4 - (payload.length % 4)) % 4),
      "="
    );
    const json = decodeURIComponent(
      atob(padded)
        .split("")
        .map((c) => `%${c.charCodeAt(0).toString(16).padStart(2, "0")}`)
        .join("")
    );
    return JSON.parse(json) as JwtClaims;
  } catch {
    return null;
  }
}

/** Normalize the roles claim (list or space/comma-delimited string) to an array. */
export function rolesOf(claims: JwtClaims | null): string[] {
  if (!claims?.roles) return [];
  if (Array.isArray(claims.roles)) return claims.roles.map(String);
  return String(claims.roles).split(/[\s,]+/).filter(Boolean);
}
