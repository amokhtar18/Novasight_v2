"""JWT verification and the ``get_principal`` FastAPI dependency.

Two modes controlled by ``AuthSettings.dev_stub``:

* **OIDC mode** (default, ``dev_stub=False``): validates RS256 tokens against
  the JWKS endpoint. JWKS keys are fetched asynchronously via ``httpx`` and
  cached per ``kid`` for the lifetime of the process. Issuer, audience, and
  expiry are checked.

* **Dev-stub mode** (``dev_stub=True``): validates HS256 tokens signed with
  ``AuthSettings.dev_stub_secret``. This mode must NEVER be enabled in
  production — ``dev_stub`` defaults to ``False`` to enforce that.

In both modes, a missing/invalid/expired token raises ``HTTPException(401)``.
A missing required claim (``sub`` or the configured tenant claim) also raises 401.

No secret values are logged or returned in error messages.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import AuthSettings, Settings, get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JWKS key cache — keyed by kid, values are PyJWT-compatible public key objects.
# The values are opaque to mypy (RSAPublicKey etc.); we type as Any to avoid
# threading the cryptography type through every call site. ANN401 is suppressed
# only inside this module's private cache — never in public API signatures.
# ---------------------------------------------------------------------------
_jwks_cache: dict[str, Any] = {}

_bearer_scheme = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Principal
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Principal:
    """The authenticated identity extracted from the verified JWT."""

    subject: str          # JWT ``sub`` claim
    tenant_key: str       # Value of the configured tenant claim (e.g. the tenant slug)
    email: str            # ``email`` claim (falls back to ``sub`` if absent)
    roles: frozenset[str] = frozenset()  # values of the configured roles claim


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_bearer(request: Request) -> str:
    """Pull the raw token from the ``Authorization: Bearer <token>`` header.

    Raises ``HTTPException(401)`` if the header is absent or not a Bearer scheme.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = auth_header[len("bearer "):].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Bearer token is empty")
    return token


async def _fetch_jwks_key(kid: str, jwks_url: str) -> Any:  # noqa: ANN401
    """Fetch JWKS from the provider and return the key matching ``kid``.

    Caches the key by kid so subsequent requests are free of network I/O.
    Raises ``HTTPException(401)`` if the kid is not found or the fetch fails.
    Returns a PyJWT-compatible public key object (type is opaque from jwt internals).
    """
    if kid in _jwks_cache:
        return _jwks_cache[kid]

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(jwks_url)
            response.raise_for_status()
            jwks_data = response.json()
    except Exception as exc:
        logger.exception("Failed to fetch JWKS from provider")
        raise HTTPException(status_code=401, detail="Unable to fetch signing keys") from exc

    keys = jwks_data.get("keys", [])
    for key_data in keys:
        key_kid = key_data.get("kid")
        try:
            loaded = jwt.algorithms.RSAAlgorithm.from_jwk(key_data)
            _jwks_cache[key_kid] = loaded
        except Exception:
            logger.warning("Could not load JWK kid=%s", key_kid)

    if kid not in _jwks_cache:
        raise HTTPException(status_code=401, detail="Unknown signing key")

    return _jwks_cache[kid]


async def _verify_oidc(token: str, auth_cfg: AuthSettings) -> dict[str, object]:
    """Verify an RS256 OIDC token.

    Checks signature, issuer, audience, and expiry.
    Returns the decoded claims dict on success.
    """
    try:
        unverified_header = jwt.get_unverified_header(token)
    except jwt.DecodeError as exc:
        raise HTTPException(status_code=401, detail="Malformed token") from exc

    kid: str = unverified_header.get("kid", "")
    public_key: Any = await _fetch_jwks_key(kid, auth_cfg.jwks_url)

    try:
        claims: dict[str, object] = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            issuer=auth_cfg.oidc_issuer,
            audience=auth_cfg.oidc_audience,
            options={"require": ["sub", "exp", "iss", "aud"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Token has expired") from exc
    except jwt.InvalidIssuerError as exc:
        raise HTTPException(status_code=401, detail="Token issuer mismatch") from exc
    except jwt.InvalidAudienceError as exc:
        raise HTTPException(status_code=401, detail="Token audience mismatch") from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Token validation failed") from exc

    return claims


def _verify_hs256(token: str, secret: str) -> dict[str, object]:
    """Verify an HS256 token signed with the shared ``secret``.

    Used by both dev-stub mode and first-class password mode — in both, the
    backend (or the dev harness) signs the token with a symmetric secret it also
    holds. Checks signature and expiry. Returns the decoded claims on success.
    """
    try:
        claims: dict[str, object] = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"require": ["sub", "exp"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Token has expired") from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Token validation failed") from exc

    return claims


def mint_token(
    *,
    secret: str,
    subject: str,
    tenant_slug: str,
    email: str,
    roles: list[str],
    ttl_seconds: int,
    tenant_claim: str,
    roles_claim: str,
    kind: str = "access",
) -> str:
    """Sign an HS256 token for password-mode auth.

    Co-located with verification so the claim shape stays in lock-step. The
    ``tenant_claim`` / ``roles_claim`` names come from settings (golden rule 1) so
    issued tokens match exactly what ``get_principal`` and ``get_tenant_context``
    read back. ``kind`` distinguishes short-lived access tokens from long-lived
    refresh tokens (carried as the ``typ`` claim; the refresh endpoint requires
    ``typ == "refresh"``).
    """
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": subject,
        "email": email,
        tenant_claim: tenant_slug,
        roles_claim: roles,
        "typ": kind,
        "iat": now,
        "exp": now + ttl_seconds,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def _extract_roles(claims: dict[str, object], roles_claim: str) -> frozenset[str]:
    """Read the roles claim as a set of strings; tolerate absence or a scalar.

    A missing claim yields an empty set (no privileges). A list yields its string
    members; a single string is treated as one role.
    """
    raw = claims.get(roles_claim)
    if isinstance(raw, str):
        return frozenset({raw})
    if isinstance(raw, (list, tuple)):
        return frozenset(item for item in raw if isinstance(item, str))
    return frozenset()


def _build_principal(
    claims: dict[str, object], tenant_claim: str, roles_claim: str
) -> Principal:
    """Extract ``Principal`` fields from verified claims.

    Raises ``HTTPException(401)`` if ``sub`` or the tenant claim are absent.
    """
    subject = claims.get("sub")
    if not subject or not isinstance(subject, str):
        raise HTTPException(status_code=401, detail="Token missing sub claim")

    tenant_key = claims.get(tenant_claim)
    if not tenant_key or not isinstance(tenant_key, str):
        raise HTTPException(
            status_code=401,
            detail=f"Token missing required claim: {tenant_claim}",
        )

    email_val = claims.get("email")
    email: str = email_val if isinstance(email_val, str) else subject
    return Principal(
        subject=subject,
        tenant_key=tenant_key,
        email=email,
        roles=_extract_roles(claims, roles_claim),
    )


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


async def get_principal(
    request: Request,
    _credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> Principal:
    """FastAPI dependency that verifies the JWT and returns the authenticated ``Principal``.

    Raises ``HTTPException(401)`` on any auth failure.  Never leaks secrets or
    internal details in the error message.
    """
    token = _extract_bearer(request)
    auth_cfg = settings.auth

    # HS256 (dev-stub or password mode) when a symmetric secret is configured;
    # otherwise real OIDC (RS256/JWKS).
    hs256_secret = auth_cfg.hs256_secret
    if hs256_secret is not None:
        claims = _verify_hs256(token, hs256_secret)
    else:
        claims = await _verify_oidc(token, auth_cfg)

    return _build_principal(claims, auth_cfg.tenant_claim, auth_cfg.roles_claim)


async def require_platform_admin(
    principal: Principal = Depends(get_principal),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> Principal:
    """Dependency: authorize a control-plane (platform-admin) caller.

    Gates the not-tenant-scoped provisioning endpoints. The required role name comes
    from ``settings.auth.platform_admin_role`` (golden rule 1), never a literal here.
    Fails closed with 403 when the principal lacks the role.
    """
    if settings.auth.platform_admin_role not in principal.roles:
        logger.warning("Principal sub=%r lacks platform-admin role", principal.subject)
        raise HTTPException(status_code=403, detail="Platform admin role required")
    return principal


async def require_tenant_editor(
    principal: Principal = Depends(get_principal),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> Principal:
    """Dependency: authorize a caller who may create/edit tenant content.

    Gates content mutations (charts, dashboards) that any tenant member may perform —
    *except* a read-only **viewer**. ``viewer`` is a restricting role: a principal
    holding it is rejected with 403 unless they also hold a role that outranks it
    (tenant superuser or platform admin). Role names come from settings (golden rule 1).
    Non-breaking: a principal with no roles is a normal member and is allowed.
    """
    auth = settings.auth
    roles = principal.roles
    is_viewer = auth.tenant_viewer_role in roles
    outranks = (
        auth.tenant_superuser_role in roles or auth.platform_admin_role in roles
    )
    if is_viewer and not outranks:
        logger.warning("Principal sub=%r is a read-only viewer", principal.subject)
        raise HTTPException(
            status_code=403, detail="Read-only (viewer) users cannot modify content"
        )
    return principal


async def require_tenant_superuser(
    principal: Principal = Depends(get_principal),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> Principal:
    """Dependency: authorize a tenant *superuser* (orchestration operator).

    Gates tenant-scoped actions that create, run, or schedule pipelines and dbt
    jobs. The required role name comes from ``settings.auth.tenant_superuser_role``
    (golden rule 1). A platform admin is implicitly allowed (they outrank tenant
    roles). Fails closed with 403 otherwise.
    """
    roles = principal.roles
    if (
        settings.auth.tenant_superuser_role not in roles
        and settings.auth.platform_admin_role not in roles
    ):
        logger.warning("Principal sub=%r lacks tenant-superuser role", principal.subject)
        raise HTTPException(status_code=403, detail="Superuser role required")
    return principal
