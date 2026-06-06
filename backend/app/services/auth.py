"""Password-authentication service: credential verification + token issuance.

The backend mints HS256 access/refresh tokens whose claim shape exactly matches
what ``app.core.security`` reads back (``sub``, the tenant claim = slug, the roles
claim, ``exp``). The tenant a token is scoped to is resolved here from the login
request (slug, defaulting to the seed tenant) — never trusted from a request body
on later calls (tenancy-isolation invariant).

Auth failures are deliberately indistinguishable (unknown tenant, unknown user,
wrong password, inactive principal all return the same 401) to avoid leaking which
part was wrong.
"""
from __future__ import annotations

import logging

import jwt
from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.core.passwords import verify_password
from app.core.security import mint_token
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.auth import AccessTokenResponse, TokenResponse, UserIdentity

logger = logging.getLogger(__name__)

_INVALID = HTTPException(status_code=401, detail="Invalid credentials")


class AuthService:
    """Verifies credentials and issues tokens for password-mode auth."""

    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self._db = db
        self._settings = settings

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def login(
        self, *, email: str, password: str, tenant_slug: str | None
    ) -> TokenResponse:
        """Verify credentials and return access + refresh tokens with identity."""
        secret = self._require_secret()
        slug = tenant_slug or self._settings.seed_tenant.slug

        tenant = await self._active_tenant(slug)
        user = await self._user(tenant.id, email)
        if user is None or not user.is_active or not user.password_hash:
            logger.info("Login rejected (no/inactive user) tenant=%r", slug)
            raise _INVALID
        if not verify_password(password, user.password_hash):
            logger.info("Login rejected (bad password) tenant=%r", slug)
            raise _INVALID

        roles = list(user.roles or [])
        access = self._mint(secret, user, slug, roles, kind="access")
        refresh = self._mint(secret, user, slug, roles, kind="refresh")
        return TokenResponse(
            access_token=access,
            refresh_token=refresh,
            expires_in=self._settings.auth.access_ttl_seconds,
            user=self._identity(user, slug, roles),
        )

    async def refresh(self, refresh_token: str) -> AccessTokenResponse:
        """Validate a refresh token and mint a fresh access token."""
        secret = self._require_secret()
        try:
            claims = jwt.decode(
                refresh_token, secret, algorithms=["HS256"], options={"require": ["sub", "exp"]}
            )
        except jwt.PyJWTError as exc:
            raise _INVALID from exc
        if claims.get("typ") != "refresh":
            raise _INVALID

        slug = str(claims.get(self._settings.auth.tenant_claim) or "")
        subject = str(claims.get("sub") or "")
        tenant = await self._active_tenant(slug)
        user = await self._db.get(User, _as_uuid(subject))
        if user is None or user.tenant_id != tenant.id or not user.is_active:
            raise _INVALID

        roles = list(user.roles or [])
        access = self._mint(secret, user, slug, roles, kind="access")
        return AccessTokenResponse(
            access_token=access, expires_in=self._settings.auth.access_ttl_seconds
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _require_secret(self) -> str:
        secret = self._settings.auth.hs256_secret
        if secret is None:
            # Password login is disabled (OIDC mode). Surface a clear 400 so the
            # caller knows to use the IdP, not a generic auth failure.
            raise HTTPException(
                status_code=400, detail="Password login is disabled (OIDC mode)"
            )
        return secret

    async def _active_tenant(self, slug: str) -> Tenant:
        result = await self._db.execute(select(Tenant).where(Tenant.slug == slug))
        tenant = result.scalars().first()
        if tenant is None or tenant.status != "active":
            raise _INVALID
        return tenant

    async def _user(self, tenant_id: object, email: str) -> User | None:
        result = await self._db.execute(
            select(User).where(User.tenant_id == tenant_id, User.email == email)
        )
        return result.scalars().first()

    def _mint(
        self, secret: str, user: User, slug: str, roles: list[str], *, kind: str
    ) -> str:
        auth = self._settings.auth
        ttl = auth.access_ttl_seconds if kind == "access" else auth.refresh_ttl_seconds
        return mint_token(
            secret=secret,
            subject=str(user.id),
            tenant_slug=slug,
            email=user.email,
            roles=roles,
            ttl_seconds=ttl,
            tenant_claim=auth.tenant_claim,
            roles_claim=auth.roles_claim,
            kind=kind,
        )

    @staticmethod
    def _identity(user: User, slug: str, roles: list[str]) -> UserIdentity:
        return UserIdentity(
            id=str(user.id), email=user.email, name=user.name, tenant=slug, roles=roles
        )


def _as_uuid(value: str) -> object:
    """Best-effort UUID coercion for ``Session.get`` (returns the raw string on failure)."""
    import uuid

    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError):
        return value


def get_auth_service(
    db: AsyncSession = Depends(get_db),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> AuthService:
    """FastAPI dependency: an ``AuthService`` wired to the request session + settings."""
    return AuthService(db, settings)
