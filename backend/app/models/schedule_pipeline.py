"""Association of reusable schedules to pipelines (#3, M:N).

A ``Schedule`` is a named cron that can drive *many* pipelines, and a pipeline can
be driven by *many* schedules. This join table is the source of truth for that
fan-out; the dispatcher reads it to enqueue a run per attached pipeline. ``tenant_id``
is denormalised so every row carries its tenant scope (see ``tenancy-isolation``).

The legacy ``schedules.target_id`` column is retained (it points at the first
attached pipeline) for backward compatibility, but the join table is authoritative.
"""
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SchedulePipeline(Base):
    """One (schedule ↔ pipeline) attachment, scoped to a tenant."""

    __tablename__ = "schedule_pipelines"

    schedule_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("schedules.id", ondelete="CASCADE"), primary_key=True
    )
    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("pipelines.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"SchedulePipeline(schedule={self.schedule_id!r}, pipeline={self.pipeline_id!r})"
