"""pipeline incremental cursor

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-17

Adds a nullable ``cursor`` JSON column to ``pipelines`` holding incremental-run state
(e.g. ``{"cdc": "<high-water mark>"}``). Nullable so existing rows need no backfill —
the executor reads NULL as "no prior run" and a first incremental run loads everything,
then advances the cursor on success. Opaque JSON so new cursor kinds need no migration.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("pipelines", sa.Column("cursor", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("pipelines", "cursor")
