"""Tenant registry — resolves a tenant slug to its DB row.

The registry is the ONLY authority for mapping an authenticated claim value
(the tenant slug) to a ``Tenant`` ORM object with its ``TenantResourceMap``.

Design decisions:
- Resolution is by ``Tenant.slug`` (the stable, human-readable handle that we
  embed in JWTs as the tenant claim value).
- The ``TenantResourceMap`` relationship is eager-loaded so callers never need
  a second query.
- A missing slug returns ``None``; the caller (``get_tenant_context``) decides
  whether to 403 or handle the absence differently — keeping the registry pure.
"""
from __future__ import annotations

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.db import get_db
from app.models.tenant import Tenant


class TenantRegistry:
    """Resolves tenant slugs to ``Tenant`` rows from the control-plane DB."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def resolve(self, slug: str) -> Tenant | None:
        """Return the ``Tenant`` whose slug matches, with ``resource_map`` loaded.

        Returns ``None`` if no tenant with that slug exists.
        Never raises for a missing tenant — the caller enforces policy.
        """
        result = await self._db.execute(
            select(Tenant)
            .where(Tenant.slug == slug)
            .options(selectinload(Tenant.resource_map))
        )
        return result.scalars().first()


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


async def get_tenant_registry(
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> TenantRegistry:
    """FastAPI dependency: return a ``TenantRegistry`` wired to the request DB session."""
    return TenantRegistry(db)
