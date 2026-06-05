"""A KPI threshold — the per-tenant alerting registry row for Phase 5.2.

A ``KpiThreshold`` records *what* to measure (a stored single-value aggregate query
over one of the tenant's datasets), the *comparator + threshold* that defines a
breach, *how* to alert (email or webhook), and *when* to evaluate (a cron schedule).
The alert worker evaluates enabled rows on each dispatcher tick.

Why a registry row (not config): thresholds, schedules, and recipients are
tenant-specific and change without a deploy, so they must not be literals or env
(golden rule 1). The SMTP relay that delivers email alerts is infrastructure and
lives in settings.

Breach state is tracked on the row itself (``is_breaching`` + ``last_fired_at``) so
a breach fires **exactly one** alert until the metric recovers — the de-dupe is the
transition from not-breaching to breaching, not the breaching condition itself.

``tenant_id`` is the isolation column; the referenced ``dataset_id`` must belong to
the same tenant, which the evaluator re-asserts at query time.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    String,
    Uuid,
    false,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

# The closed set of comparators a KPI may use (also enforced at evaluation time).
_COMPARATORS = ("'>'", "'<'", "'>='", "'<='", "'=='", "'!='")

if TYPE_CHECKING:
    from app.models.dataset import Dataset
    from app.models.tenant import Tenant


class KpiThreshold(TimestampMixin, Base):
    """One KPI threshold owned by a tenant."""

    __tablename__ = "kpi_thresholds"
    __table_args__ = (
        # Persistence-layer guard: reject any comparator outside the closed set,
        # so a mis-entered value is caught at write time, not only at evaluation.
        CheckConstraint(
            f"comparator IN ({', '.join(_COMPARATORS)})",
            name="ck_kpi_thresholds_comparator",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Serialized ``QueryRequest`` producing a single aggregate value (no dimensions).
    query_spec: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    # Comparator defining a breach: one of > < >= <= == != (validated on evaluate).
    comparator: Mapped[str] = mapped_column(String(2), nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    # Five-field cron deciding when the KPI is evaluated (tenant config).
    schedule: Mapped[str] = mapped_column(String(128), nullable=False)
    # Delivery channel + its target. "email" uses ``recipients``; "webhook" uses ``webhook_url``.
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    recipients: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    webhook_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )

    # --- Exactly-once breach state ---
    is_breaching: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    last_fired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    tenant: Mapped[Tenant] = relationship()
    dataset: Mapped[Dataset] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"KpiThreshold(id={self.id!r}, tenant_id={self.tenant_id!r}, "
            f"name={self.name!r}, comparator={self.comparator!r}, threshold={self.threshold!r})"
        )
