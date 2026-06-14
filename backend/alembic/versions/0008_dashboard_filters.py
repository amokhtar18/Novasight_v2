"""dashboard view-time filters

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-15

Adds a nullable ``filters`` JSON column to ``dashboards`` holding the dashboard's
view-time filters (a list of SemanticFilter dicts). Nullable so existing rows need
no backfill; the service reads NULL as an empty list. Each filter member is
re-validated by the semantic query path, so this column never widens data access.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("dashboards", sa.Column("filters", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("dashboards", "filters")
