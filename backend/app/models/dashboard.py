"""Dashboards and their tiles — persisted, replacing the client-side store.

A ``Dashboard`` is an ordered grid of ``DashboardTile`` rows, each referencing a
saved ``Chart`` with its grid position/size. Persisting server-side means
dashboards are shareable and survive across devices (the old localStorage store is
superseded). Both tenant-scoped (see ``tenancy-isolation``).
"""
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Dashboard(TimestampMixin, Base):
    """A named collection of chart tiles, scoped to one tenant."""

    __tablename__ = "dashboards"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    tiles: Mapped[list[DashboardTile]] = relationship(
        back_populates="dashboard",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="DashboardTile.position",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"Dashboard(id={self.id!r}, tenant_id={self.tenant_id!r}, name={self.name!r})"


class DashboardTile(TimestampMixin, Base):
    """One placed chart on a dashboard (grid position + size)."""

    __tablename__ = "dashboard_tiles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    dashboard_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dashboards.id", ondelete="CASCADE"), index=True, nullable=False
    )
    chart_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("charts.id", ondelete="CASCADE"), nullable=False
    )
    # Optional per-tile title override (defaults to the chart's name).
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Ordering + simple grid layout (12-col grid convention; w/h in grid units).
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    x: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    y: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    w: Mapped[int] = mapped_column(Integer, nullable=False, default=6, server_default="6")
    h: Mapped[int] = mapped_column(Integer, nullable=False, default=4, server_default="4")

    dashboard: Mapped[Dashboard] = relationship(back_populates="tiles")

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"DashboardTile(id={self.id!r}, chart_id={self.chart_id!r})"
