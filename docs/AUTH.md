# Authentication, identity & user management

NovaSight verifies a JWT on every request and resolves the tenant from a verified
claim — never from the request body (see `tenancy-isolation`). There are three
auth modes, selected by configuration (golden rule 1); the request-side
verification and tenant resolution are identical across all three.

## Modes (`app/core/config.py: AuthSettings`)

| Mode | When active | Token | Login |
|------|-------------|-------|-------|
| **password** (default) | `AUTH__SESSION_SECRET` set, `dev_stub` off | HS256, signed by the backend | `POST /api/v1/auth/login` |
| **dev-stub** | `AUTH__DEV_STUB=true` | HS256, signed by the dev harness | tokens minted by tests/tooling |
| **OIDC** | neither secret set | RS256, verified via JWKS | external IdP |

`AuthSettings.hs256_secret` returns the active symmetric secret (dev-stub or
password); when it is `None`, real OIDC is in force and the `/auth/login` endpoints
return 400.

## Password login flow

1. `POST /api/v1/auth/login` `{email, password, tenant?}` — `tenant` is the slug;
   omitted ⇒ the configured seed tenant (single-tenant on-prem). Returns
   `{access_token, refresh_token, token_type, expires_in, user}`.
2. The client sends `Authorization: Bearer <access_token>` on every call.
3. `POST /api/v1/auth/refresh` `{refresh_token}` → a fresh access token.
4. `POST /api/v1/auth/logout` → 204 (stateless; the client discards its tokens).

Tokens are minted by `app/core/security.py: mint_token` with the exact claim shape
`get_principal` reads back: `sub` (user id), `email`, the tenant claim (= slug),
the roles claim (list), `typ` (`access`|`refresh`), `iat`, `exp`. Refresh tokens
carry `typ=refresh`; the refresh endpoint rejects anything else. Auth failures are
deliberately indistinguishable (unknown tenant/user, wrong password, inactive all
return 401).

`GET /api/v1/me` returns the resolved tenant context **plus** the verified identity
(`subject`, `email`, `tenant`, `roles`) so the frontend renders the signed-in user
from a server-verified source instead of decoding the token itself.

## Roles & authorization

Roles live on the `users` row (`roles` JSON list) and are embedded into the issued
token. Two role gates back the dependencies in `app/core/security.py`:

- **`platform_admin`** (`AUTH__PLATFORM_ADMIN_ROLE`) — `require_platform_admin`;
  the cross-tenant control plane (provision/de-provision/list tenants). Not
  tenant-scoped.
- **`superuser`** (`AUTH__TENANT_SUPERUSER_ROLE`) — `require_tenant_superuser`;
  tenant-scoped orchestration and user management. A platform admin is implicitly
  allowed.

## User management (`/api/v1/users`, tenant-scoped)

`GET` / `POST` / `PATCH /{id}` / `DELETE /{id}`, all scoped to the caller's tenant
and gated by `require_tenant_superuser`. Email is unique within a tenant; passwords
are write-only (bcrypt, `app/core/passwords.py`). A tenant superuser **cannot**
grant the `platform_admin` role — only a platform admin can (escalation guard in
`app/api/v1/users.py`).

## Tenant management (`/api/v1/tenants`, platform admin)

`GET` (list), `GET /{slug}`, `POST` (provision), `DELETE /{slug}` (de-provision).

## Seeding

`python -m app.scripts.seed` creates the bootstrap tenant + admin. When
`SEED_TENANT__ADMIN_PASSWORD` is set (password mode), the admin gets a usable login
and the `platform_admin` + `superuser` roles so the install is operable out of the
box. In OIDC mode, omit it — the admin user exists but has no local password.
