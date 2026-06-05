"""datasets.sensitive_columns: column-level encryption tags

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-05

Adds the nullable ``sensitive_columns`` JSON column to ``datasets`` (Phase 5.4):
the list of logical column names that are encrypted at rest and masked/revealed on
read. Nullable with no server default so the migration is dialect-portable.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "datasets",
        sa.Column("sensitive_columns", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("datasets", "sensitive_columns")
