"""A user belongs to exactly one tenant.

Users are scoped to their tenant: the authenticated principal's tenant claim is
the only authority for which rows are visible (see ``tenancy-isolation``).
Email is unique *within* a tenant, not globally, so the same address can exist
in two separate tenants without collision.
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.tenant import Tenant


class User(TimestampMixin, Base):
    """An identity within a tenant."""

    __tablename__ = "users"
    __table_args__ = (
        # Email is unique per tenant, not across the whole table.
        UniqueConstraint("tenant_id", "email", name="uq_users_tenant_id_email"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    # Human-facing display name (optional; falls back to email in the UI).
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # bcrypt hash for password-auth users; NULL for OIDC-provisioned identities
    # (their credentials live with the external IdP).
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Tenant-scoped roles embedded into the issued JWT's roles claim. JSON list keeps
    # the migration dialect-portable (Postgres + the SQLite test DB). NULL == no roles.
    roles: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    tenant: Mapped[Tenant] = relationship(back_populates="users")

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"User(id={self.id!r}, tenant_id={self.tenant_id!r}, email={self.email!r})"
