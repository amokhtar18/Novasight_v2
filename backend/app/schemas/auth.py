"""Request/response schemas for password authentication.

Password login is only active when the backend is configured for HS256 token
issuance (``settings.auth.hs256_secret`` is set — dev-stub or password mode).
In OIDC mode these endpoints are disabled and tokens come from the external IdP.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """Credentials for ``POST /auth/login``.

    ``tenant`` is the tenant *slug*; when omitted, the server uses the configured
    seed tenant (the common single-tenant on-prem case). The tenant in the issued
    token always comes from this lookup — never trusted later from a request body.
    """

    email: str = Field(..., min_length=1, max_length=320)
    password: str = Field(..., min_length=1, max_length=128)
    tenant: str | None = Field(
        default=None, max_length=63, description="Tenant slug; defaults to the seed tenant."
    )


class UserIdentity(BaseModel):
    """The authenticated user's display identity (no secrets)."""

    id: str
    email: str
    name: str | None
    tenant: str
    roles: list[str]


class TokenResponse(BaseModel):
    """Issued tokens + the user's identity, returned on successful login."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 — OAuth2 response field, not a credential
    expires_in: int = Field(description="Access-token lifetime in seconds.")
    user: UserIdentity


class RefreshRequest(BaseModel):
    """Body for ``POST /auth/refresh``."""

    refresh_token: str = Field(..., min_length=1)


class AccessTokenResponse(BaseModel):
    """A freshly minted access token (refresh flow)."""

    access_token: str
    token_type: str = "bearer"  # noqa: S105 — OAuth2 response field, not a credential
    expires_in: int
