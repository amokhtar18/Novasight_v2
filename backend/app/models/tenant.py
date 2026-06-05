"""Tenant and its resource mapping — the heart of the control plane.

A ``Tenant`` is the unit of isolation. Its physical resources (Iceberg
namespace, ClickHouse database, dbt schema) are recorded once in
``TenantResourceMap`` so that every data-touching code path resolves *where* a
tenant's data lives from this single authority — never by guessing or by
trusting a client-supplied value (see the ``tenancy-isolation`` skill).

On-prem single-tenant installs hold exactly one ``Tenant`` row; the cloud
multi-tenant deployment holds many. The code path is identical either way.
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.tenant_resource_map import TenantResourceMap
    from app.models.user import User


class Tenant(TimestampMixin, Base):
    """A customer/workspace boundary. Owns users and one resource mapping."""

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    # Slug is the human-stable handle used to derive resource names; immutable.
    slug: Mapped[str] = mapped_column(String(63), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Lifecycle: "active" | "suspended". Kept as a plain string (no DB enum) so
    # adding states later needs no migration of an enum type.
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active", server_default="active"
    )

    resource_map: Mapped[TenantResourceMap] = relationship(
        back_populates="tenant",
        cascade="all, delete-orphan",
        uselist=False,
        passive_deletes=True,
    )
    users: Mapped[list[User]] = relationship(
        back_populates="tenant",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"Tenant(id={self.id!r}, slug={self.slug!r})"
