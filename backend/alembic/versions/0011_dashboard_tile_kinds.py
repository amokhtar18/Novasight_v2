"""generalize dashboard tiles: kind + content, nullable chart_id (#10)

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-21

Lets a dashboard hold decoration tiles (text / markdown / image / divider / filter)
alongside pinned charts. Adds a ``kind`` discriminator (default ``chart`` so existing
rows stay chart tiles) and a ``content`` JSON payload, and makes ``chart_id`` nullable.

The ``chart_id`` nullability change runs in a batch (table-copy) so it is portable to
SQLite, which the migration test exercises.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "dashboard_tiles",
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="chart"),
    )
    op.add_column("dashboard_tiles", sa.Column("content", sa.JSON(), nullable=True))
    with op.batch_alter_table("dashboard_tiles") as batch:
        batch.alter_column("chart_id", existing_type=sa.Uuid(), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("dashboard_tiles") as batch:
        batch.alter_column("chart_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_column("dashboard_tiles", "content")
    op.drop_column("dashboard_tiles", "kind")
