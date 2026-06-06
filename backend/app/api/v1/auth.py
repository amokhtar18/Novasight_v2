"""Authentication endpoints — password login, refresh, logout.

Thin router: delegates credential verification and token issuance to
``AuthService``. Active only in HS256 (dev-stub / password) mode; in OIDC mode the
external IdP issues tokens and ``/auth/login`` returns 400.

Logout is stateless: tokens are short-lived bearer tokens with no server-side
session, so logout is a client-side discard (the endpoint exists for symmetry and
future denylist support).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from app.schemas.auth import (
    AccessTokenResponse,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
)
from app.services.auth import AuthService, get_auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    svc: AuthService = Depends(get_auth_service),  # noqa: B008
) -> TokenResponse:
    """Verify credentials and return access + refresh tokens with the user identity."""
    return await svc.login(
        email=payload.email, password=payload.password, tenant_slug=payload.tenant
    )


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh(
    payload: RefreshRequest,
    svc: AuthService = Depends(get_auth_service),  # noqa: B008
) -> AccessTokenResponse:
    """Exchange a valid refresh token for a fresh access token."""
    return await svc.refresh(payload.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout() -> Response:
    """Stateless logout — the client discards its tokens."""
    return Response(status_code=status.HTTP_204_NO_CONTENT)
