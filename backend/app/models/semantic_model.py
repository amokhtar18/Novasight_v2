"""A semantic model — the governed metric/dimension layer (Cube) definition.

A wizard-defined cube over a ClickHouse serving table (a dbt mart): measures,
dimensions, joins, and time dimensions live in ``config``. The codegen layer
renders this into the per-tenant Cube data model; the AI layer and the manual
chart builder query *this*, never raw tables. Scoped to one tenant.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class SemanticModel(TimestampMixin, Base):
    """A Cube cube/view definition over a serving table, scoped to one tenant."""

    __tablename__ = "semantic_models"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Physical serving table (ClickHouse) this model is built over.
    base_table: Mapped[str] = mapped_column(String(255), nullable=False)
    # measures / dimensions / joins / time dimensions.
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"SemanticModel(id={self.id!r}, tenant_id={self.tenant_id!r}, name={self.name!r})"
