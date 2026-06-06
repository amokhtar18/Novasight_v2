"""Tenant-scoped user management endpoints.

All routes resolve the tenant from the JWT (``get_tenant_context``) and require the
tenant *superuser* role (``require_tenant_superuser``) — a platform admin is
implicitly allowed. There is no tenant id in any path or body by design.

Privilege-escalation guard: only a platform admin may grant or keep the
platform-admin role on a user; a tenant superuser cannot mint a platform admin.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.core.config import Settings, get_settings
from app.core.security import Principal, require_tenant_superuser
from app.models.user import User
from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.services.users import UserService, get_user_service
from app.tenancy.context import TenantContext, get_tenant_context

router = APIRouter(prefix="/users", tags=["users"])


def _to_read(user: User) -> UserRead:
    return UserRead(
        id=str(user.id),
        email=user.email,
        name=user.name,
        roles=list(user.roles or []),
        is_active=user.is_active,
    )


def _guard_role_assignment(
    roles: list[str] | None, principal: Principal, settings: Settings
) -> None:
    """Block a non-platform-admin from assigning the platform-admin role.

    Prevents a tenant superuser from escalating a user (or themselves) to the
    cross-tenant control-plane role. No-op when ``roles`` is None (not being set).
    """
    if roles is None:
        return
    admin_role = settings.auth.platform_admin_role
    if admin_role in roles and admin_role not in principal.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a platform admin can grant the platform-admin role",
        )


@router.get("", response_model=list[UserRead])
async def list_users(
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    _: Principal = Depends(require_tenant_superuser),  # noqa: B008
    svc: UserService = Depends(get_user_service),  # noqa: B008
) -> list[UserRead]:
    """List the caller's tenant's users."""
    return [_to_read(u) for u in await svc.list_for_tenant(ctx)]


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    principal: Principal = Depends(require_tenant_superuser),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
    svc: UserService = Depends(get_user_service),  # noqa: B008
) -> UserRead:
    """Create a user in the caller's tenant."""
    _guard_role_assignment(payload.roles, principal, settings)
    return _to_read(await svc.create(ctx, payload))


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    principal: Principal = Depends(require_tenant_superuser),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
    svc: UserService = Depends(get_user_service),  # noqa: B008
) -> UserRead:
    """Update a user (partial) in the caller's tenant."""
    _guard_role_assignment(payload.roles, principal, settings)
    return _to_read(await svc.update(ctx, user_id, payload))


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    _: Principal = Depends(require_tenant_superuser),  # noqa: B008
    svc: UserService = Depends(get_user_service),  # noqa: B008
) -> Response:
    """Delete a user in the caller's tenant."""
    await svc.delete(ctx, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
