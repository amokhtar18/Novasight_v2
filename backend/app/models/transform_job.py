"""A transform job — a runnable/schedulable unit of dbt work.

Bundles a dbt selection (which models to build) into a named job the API can run
now or schedule via Dagster, mirroring how pipelines are run/scheduled. Scoped to
one tenant (see ``tenancy-isolation``).
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class TransformJob(TimestampMixin, Base):
    """A named dbt build job (a dbt selector + options), scoped to one tenant."""

    __tablename__ = "transform_jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # dbt selector string (e.g. "marts.*" or specific model names); empty == all.
    selection: Mapped[str] = mapped_column(
        String(512), nullable=False, default="", server_default=""
    )
    # Extra run options (full_refresh, vars, ...).
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"TransformJob(id={self.id!r}, tenant_id={self.tenant_id!r}, name={self.name!r})"
