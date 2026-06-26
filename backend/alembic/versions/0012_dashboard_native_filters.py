"""dashboard native filters (Slice C)

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-26

Replaces the single ``filters`` JSON column with ``native_filters`` (a list of
NativeFilter config dicts). Fresh-start: the old flat filters are dropped (pre-prod,
no backfill). The drop runs in a batch so it stays portable to SQLite (migration test).
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("dashboards", sa.Column("native_filters", sa.JSON(), nullable=True))
    with op.batch_alter_table("dashboards") as batch:
        batch.drop_column("filters")


def downgrade() -> None:
    op.add_column("dashboards", sa.Column("filters", sa.JSON(), nullable=True))
    with op.batch_alter_table("dashboards") as batch:
        batch.drop_column("native_filters")
