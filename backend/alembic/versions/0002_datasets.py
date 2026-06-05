"""datasets: tenant-scoped uploaded source objects

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-05

Adds the ``datasets`` table recording each uploaded source object and where its
raw bytes live in the object store. Mirrors ``app.models.dataset`` exactly;
constraint/index names follow the metadata naming convention so downgrade is
reversible.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "datasets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="uploaded", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_datasets_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_datasets")),
        sa.UniqueConstraint("object_key", name=op.f("uq_datasets_object_key")),
    )
    op.create_index(op.f("ix_datasets_tenant_id"), "datasets", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_datasets_tenant_id"), table_name="datasets")
    op.drop_table("datasets")
