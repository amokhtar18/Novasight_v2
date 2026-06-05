"""kpi_thresholds: per-tenant KPI alert registry

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-05

Adds the ``kpi_thresholds`` table backing Phase 5.2 KPI alerts. Mirrors
``app.models.kpi_threshold`` exactly; constraint/index names follow the metadata
naming convention so downgrade is reversible.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "kpi_thresholds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("query_spec", sa.JSON(), nullable=False),
        sa.Column("comparator", sa.String(length=2), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("schedule", sa.String(length=128), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("recipients", sa.JSON(), nullable=True),
        sa.Column("webhook_url", sa.String(length=2048), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("is_breaching", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("last_fired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_kpi_thresholds_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.id"],
            name=op.f("fk_kpi_thresholds_dataset_id_datasets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kpi_thresholds")),
        sa.CheckConstraint(
            "comparator IN ('>', '<', '>=', '<=', '==', '!=')",
            name="ck_kpi_thresholds_comparator",
        ),
    )
    op.create_index(
        op.f("ix_kpi_thresholds_tenant_id"),
        "kpi_thresholds",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_kpi_thresholds_tenant_id"), table_name="kpi_thresholds")
    op.drop_table("kpi_thresholds")
