"""report_definitions: per-tenant scheduled report registry

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-05

Adds the ``report_definitions`` table backing Phase 5.1 scheduled Excel reports.
Mirrors ``app.models.report_definition`` exactly; constraint/index names follow
the metadata naming convention so downgrade is reversible.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "report_definitions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("query_spec", sa.JSON(), nullable=False),
        sa.Column("schedule", sa.String(length=128), nullable=False),
        sa.Column("recipients", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_report_definitions_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.id"],
            name=op.f("fk_report_definitions_dataset_id_datasets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report_definitions")),
    )
    op.create_index(
        op.f("ix_report_definitions_tenant_id"),
        "report_definitions",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_report_definitions_tenant_id"), table_name="report_definitions")
    op.drop_table("report_definitions")
