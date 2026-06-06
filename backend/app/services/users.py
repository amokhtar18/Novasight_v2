"""Tenant-scoped user management business logic.

Every query filters on ``ctx.tenant_id`` so one tenant can never see or mutate
another tenant's users (tenancy-isolation invariant). A user not owned by the
caller's tenant is indistinguishable from one that does not exist — both 404.

Authorization (who may manage users) is enforced in the router via
``require_tenant_superuser``; this service only enforces tenant scoping and
data-integrity rules (unique email within tenant, password hashing).
"""
from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.passwords import hash_password
from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate
from app.tenancy.context import TenantContext


class UserService:
    """List, create, update, and delete users within one tenant."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def list_for_tenant(self, ctx: TenantContext) -> list[User]:
        result = await self._db.execute(
            select(User)
            .where(User.tenant_id == uuid.UUID(ctx.tenant_id))
            .order_by(User.email.asc())
        )
        return list(result.scalars().all())

    async def get_for_tenant(self, ctx: TenantContext, user_id: uuid.UUID) -> User:
        result = await self._db.execute(
            select(User).where(
                User.id == user_id, User.tenant_id == uuid.UUID(ctx.tenant_id)
            )
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        return user

    async def create(self, ctx: TenantContext, data: UserCreate) -> User:
        if await self._email_taken(ctx, data.email):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A user with that email already exists in this tenant",
            )
        user = User(
            tenant_id=uuid.UUID(ctx.tenant_id),
            email=data.email,
            name=data.name,
            password_hash=hash_password(data.password),
            roles=list(data.roles),
            is_active=True,
        )
        self._db.add(user)
        await self._db.flush()
        await self._db.refresh(user)
        return user

    async def update(
        self, ctx: TenantContext, user_id: uuid.UUID, data: UserUpdate
    ) -> User:
        user = await self.get_for_tenant(ctx, user_id)
        if data.name is not None:
            user.name = data.name
        if data.roles is not None:
            user.roles = list(data.roles)
        if data.is_active is not None:
            user.is_active = data.is_active
        if data.password is not None:
            user.password_hash = hash_password(data.password)
        await self._db.flush()
        await self._db.refresh(user)
        return user

    async def delete(self, ctx: TenantContext, user_id: uuid.UUID) -> None:
        user = await self.get_for_tenant(ctx, user_id)
        await self._db.delete(user)
        await self._db.flush()

    async def _email_taken(self, ctx: TenantContext, email: str) -> bool:
        result = await self._db.execute(
            select(User.id).where(
                User.tenant_id == uuid.UUID(ctx.tenant_id), User.email == email
            )
        )
        return result.first() is not None


def get_user_service(db: AsyncSession = Depends(get_db)) -> UserService:  # noqa: B008
    """FastAPI dependency: assemble a ``UserService`` from request scope."""
    return UserService(db)
