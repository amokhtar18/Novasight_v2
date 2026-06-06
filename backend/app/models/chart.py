"""A saved chart — a persisted ChartSpec, manual or AI-generated.

Stores the declarative ``ChartSpec`` (the shared contract rendered by the frontend
``ChartRenderer``) plus where its data comes from (``source_kind`` =
semantic | dataset, ``source_ref`` = the model/dataset id). Charts are the unit
dashboards compose. Scoped to one tenant (see ``tenancy-isolation``).
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import JSON, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Chart(TimestampMixin, Base):
    """A saved chart specification, scoped to one tenant."""

    __tablename__ = "charts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # The full ChartSpec (version/type/query/encoding/options) — same shape the
    # renderer + AI NL→chart use, so manual and AI charts persist identically.
    spec: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    # Where the data comes from: "semantic" (a SemanticModel) or "dataset".
    source_kind: Mapped[str] = mapped_column(
        String(32), nullable=False, default="semantic", server_default="semantic"
    )
    # The referenced semantic model / dataset id (string form), when applicable.
    source_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Optional owner (the creating user); NULL keeps it tenant-shared.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"Chart(id={self.id!r}, tenant_id={self.tenant_id!r}, name={self.name!r})"
