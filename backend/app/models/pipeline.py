"""ETL pipeline definitions and their run history.

A ``Pipeline`` binds a ``SourceConnection`` to a selection (tables/query, write
disposition, target Iceberg table) — it is the durable definition the dynamic
Dagster code location materializes and the API runs/schedules. ``PipelineRun``
records each execution (status, rows, the Dagster run id, timings). Both are
tenant-scoped (see ``tenancy-isolation``).
"""
from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Pipeline(TimestampMixin, Base):
    """A source→Iceberg ETL definition, scoped to one tenant."""

    __tablename__ = "pipelines"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    source_connection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("source_connections.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Selection + load options (tables/query, write disposition, incremental keys).
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # Target Iceberg table name in the tenant's namespace (the curated landing table).
    target_table: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    runs: Mapped[list[PipelineRun]] = relationship(
        back_populates="pipeline", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"Pipeline(id={self.id!r}, tenant_id={self.tenant_id!r}, name={self.name!r})"


class PipelineRun(TimestampMixin, Base):
    """One execution of a ``Pipeline``."""

    __tablename__ = "pipeline_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("pipelines.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Lifecycle: queued -> running -> success | error.
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="queued", server_default="queued"
    )
    # The Dagster run id this execution maps to (for cross-linking the run UI).
    dagster_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rows: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    started_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    pipeline: Mapped[Pipeline] = relationship(back_populates="runs")

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"PipelineRun(id={self.id!r}, status={self.status!r})"
