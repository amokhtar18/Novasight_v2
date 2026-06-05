"""A dataset is one uploaded source object (e.g. a CSV) owned by a tenant.

This row is the control-plane record of *what* was uploaded and *where the raw
bytes live* (``object_key`` in the configured bucket). Downstream phases turn it
into an Iceberg table and a ClickHouse-queryable dataset, but the upload step
only needs to durably record the object and scope it to its tenant.

``tenant_id`` is the isolation column: every read of datasets filters on it, and
it is set from the server-resolved ``TenantContext`` — never from the client
(see the ``tenancy-isolation`` skill).
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.tenant import Tenant


class Dataset(TimestampMixin, Base):
    """A single uploaded source object, scoped to one tenant."""

    __tablename__ = "datasets"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    # Human-facing name; defaults to the original filename at upload time.
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    # Full key of the raw object in the configured bucket, already tenant-prefixed.
    object_key: Mapped[str] = mapped_column(String(1024), unique=True, nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Lifecycle: "uploaded" -> (later) "ingested" -> ... . Plain string, no DB enum
    # so new states need no enum-type migration.
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="uploaded", server_default="uploaded"
    )

    tenant: Mapped[Tenant] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"Dataset(id={self.id!r}, tenant_id={self.tenant_id!r}, name={self.name!r})"
