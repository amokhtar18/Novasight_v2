"""users: add auth fields (name, password_hash, roles)

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-06

Adds the columns backing password authentication and tenant-scoped roles to the
``users`` table (Phase 0 login + user management). Mirrors ``app.models.user``.
All columns are nullable so the migration is safe on existing rows; the seed
script and the user-management API populate them going forward.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("name", sa.String(length=255), nullable=True))
    op.add_column(
        "users", sa.Column("password_hash", sa.String(length=255), nullable=True)
    )
    op.add_column("users", sa.Column("roles", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "roles")
    op.drop_column("users", "password_hash")
    op.drop_column("users", "name")
