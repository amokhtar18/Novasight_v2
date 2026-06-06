"""A source connection — where a tenant's ETL pipeline pulls data from.

Holds the non-secret connection config in ``config`` (host, port, database,
bucket, path, …) and any credentials as an opaque encrypted blob in
``secret_ciphertext`` (envelope-encrypted via ``app.core.crypto`` by the service
layer — the model never sees plaintext). Scoped to one tenant like every
data-touching row (see ``tenancy-isolation``).
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.tenant import Tenant


class SourceConnection(TimestampMixin, Base):
    """A reusable connection to a data source, scoped to one tenant."""

    __tablename__ = "source_connections"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Connector kind handled by app.ingestion.connectors (e.g. "sql_database",
    # "filesystem"). Plain string so adding connectors needs no enum migration.
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    # Non-secret connection parameters (host/port/database/bucket/path/...).
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # Envelope-encrypted credentials blob (password/keys); NULL when none needed.
    secret_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active", server_default="active"
    )

    tenant: Mapped[Tenant] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"SourceConnection(id={self.id!r}, tenant_id={self.tenant_id!r}, kind={self.kind!r})"
