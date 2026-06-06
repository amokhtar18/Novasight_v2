"""A schedule — a cron binding for a pipeline or transform job, run via Dagster.

Lets a tenant superuser schedule orchestration from the app without opening
Dagster: the backend toggles the matching Dagster schedule via the GraphQL client,
and the dynamic code location builds schedules from these rows. Scoped to one
tenant (see ``tenancy-isolation``).
"""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Schedule(TimestampMixin, Base):
    """A cron schedule targeting a pipeline or transform job, scoped to one tenant."""

    __tablename__ = "schedules"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # What this schedule runs: "pipeline" | "transform_job".
    target_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    # The pipeline / transform_job id (kept generic; integrity enforced in the service).
    target_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    # Standard 5-field cron expression.
    cron: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # The Dagster schedule name this maps to (set when registered with Dagster).
    dagster_schedule_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"Schedule(id={self.id!r}, target={self.target_kind!r})"
