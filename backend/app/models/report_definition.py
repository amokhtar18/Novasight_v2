"""A scheduled report definition — the per-tenant registry row for Phase 5.1.

A ``ReportDefinition`` records *what* to render, *when*, and *to whom*: a stored
structured query against one of the tenant's datasets, a cron schedule, and a
list of recipient email addresses. The reporting worker reads these rows on each
dispatcher tick and enqueues the due ones.

Why a registry row (not config): schedule and recipients are tenant-specific and
change without a deploy, so they must NOT be literals or env (golden rule 1). The
SMTP relay that *delivers* the report is infrastructure and lives in settings.

``tenant_id`` is the isolation column: it is set from a server-resolved tenant
scope and every read filters on it. The referenced ``dataset_id`` must belong to
the same tenant — the reporting service re-asserts this at render time so a
mis-pointed row can never read another tenant's data (see ``tenancy-isolation``).
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, ForeignKey, String, Uuid, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.dataset import Dataset
    from app.models.tenant import Tenant


class ReportDefinition(TimestampMixin, Base):
    """One scheduled report owned by a tenant."""

    __tablename__ = "report_definitions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    # Dataset whose data the report renders. Must belong to the same tenant; the
    # service re-checks ownership at render time (defence in depth).
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Serialized ``QueryRequest`` (structured aggregation, never free SQL). Stored as
    # JSON and validated back into the schema before execution.
    query_spec: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    # Five-field cron expression deciding when the report runs (tenant config).
    schedule: Mapped[str] = mapped_column(String(128), nullable=False)
    # Recipient email addresses (JSON list of strings) — tenant config, not env.
    recipients: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    # Soft on/off switch so a report can be paused without deleting its history.
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )

    tenant: Mapped[Tenant] = relationship()
    dataset: Mapped[Dataset] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"ReportDefinition(id={self.id!r}, tenant_id={self.tenant_id!r}, "
            f"name={self.name!r}, schedule={self.schedule!r})"
        )
