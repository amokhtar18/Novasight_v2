"""User-authored dbt models and tests (the dbt wizard registry).

A ``DbtModel`` is a wizard-defined transformation (upstream refs, columns,
aggregations, joins in ``config``; optional generated/custom ``sql``) that the
codegen layer renders into the per-tenant dbt project and Dagster materializes to
ClickHouse. ``DbtTest`` is a wizard-defined data test attached to a model/column,
surfaced as a Dagster asset check. Both tenant-scoped (see ``tenancy-isolation``).
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class DbtModel(TimestampMixin, Base):
    """A wizard-defined dbt model, scoped to one tenant."""

    __tablename__ = "dbt_models"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Layer: staging | intermediate | marts.
    layer: Mapped[str] = mapped_column(
        String(32), nullable=False, default="marts", server_default="marts"
    )
    # Materialization: view | table | incremental.
    materialization: Mapped[str] = mapped_column(
        String(32), nullable=False, default="table", server_default="table"
    )
    # Wizard spec (source/upstream selection, columns, aggregations, joins, filters).
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # Generated SQL (or custom SQL when the user edits it directly).
    sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    tests: Mapped[list[DbtTest]] = relationship(
        back_populates="dbt_model", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"DbtModel(id={self.id!r}, tenant_id={self.tenant_id!r}, name={self.name!r})"


class DbtTest(TimestampMixin, Base):
    """A wizard-defined dbt test attached to a model (and optionally a column)."""

    __tablename__ = "dbt_tests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    dbt_model_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dbt_models.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # NULL for model-level tests; set for column-level tests.
    column_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # not_null | unique | accepted_values | relationships | ... .
    test_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # Extra parameters (e.g. accepted_values list, relationships ref/field).
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    dbt_model: Mapped[DbtModel] = relationship(back_populates="tests")

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"DbtTest(id={self.id!r}, test_type={self.test_type!r})"
