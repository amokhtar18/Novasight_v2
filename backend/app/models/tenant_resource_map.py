"""The authoritative mapping from a tenant to its physical data resources.

Each tenant's data is isolated into its own Iceberg namespace, ClickHouse
database, and dbt target schema (see ``docs/ARCHITECTURE.md`` and the
``tenancy-isolation`` skill). Those names are *derived once* from the tenant's
slug at provisioning time (``app.tenancy.resources``) and then persisted here so
the rest of the system reads them rather than recomputing — making this table
the single source of truth for "where does tenant X's data live?".

The row is one-to-one with its tenant (unique FK) and is deleted with it.
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.tenant import Tenant


class TenantResourceMap(TimestampMixin, Base):
    """Per-tenant physical resource names. One row per tenant."""

    __tablename__ = "tenant_resource_maps"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    # Globally unique so two tenants can never collide on a physical resource.
    iceberg_namespace: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    clickhouse_db: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    dbt_schema: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)

    tenant: Mapped[Tenant] = relationship(back_populates="resource_map")

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"TenantResourceMap(tenant_id={self.tenant_id!r}, "
            f"clickhouse_db={self.clickhouse_db!r})"
        )
