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


def _verify_dev_stub(token: str, auth_cfg: AuthSettings) -> dict[str, object]:
    """Verify an HS256 dev-stub token.

    ONLY called when ``auth_cfg.dev_stub is True``. Checks signature and expiry.
    Returns the decoded claims dict on success.
    """
    if auth_cfg.dev_stub_secret is None:
        raise HTTPException(
            status_code=401,
            detail="Dev-stub mode is enabled but no secret is configured",
        )

    secret = auth_cfg.dev_stub_secret.get_secret_value()
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


def _build_principal(claims: dict[str, object], tenant_claim: str) -> Principal:
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
    return Principal(subject=subject, tenant_key=tenant_key, email=email)


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

    if auth_cfg.dev_stub:
        claims = _verify_dev_stub(token, auth_cfg)
    else:
        claims = await _verify_oidc(token, auth_cfg)

    return _build_principal(claims, auth_cfg.tenant_claim)
