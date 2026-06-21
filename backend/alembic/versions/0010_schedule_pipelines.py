"""reusable schedules: schedule↔pipeline join table (#3)

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-21

Introduces a ``schedule_pipelines`` join table so one schedule can drive many
pipelines (and vice-versa). Existing 1:1 schedules are backfilled from
``schedules.target_id`` so nothing stops running across the change.

``schedules.target_id`` is intentionally left in place (it points at the first
attached pipeline) — keeping the migration ALTER-free keeps it portable to SQLite,
which the migration test exercises. The join table is the authoritative fan-out
source going forward.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "schedule_pipelines",
        sa.Column("schedule_id", sa.Uuid(), nullable=False),
        sa.Column("pipeline_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["schedule_id"], ["schedules.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pipeline_id"], ["pipelines.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("schedule_id", "pipeline_id"),
    )
    op.create_index(
        "ix_schedule_pipelines_tenant_id", "schedule_pipelines", ["tenant_id"]
    )
    op.create_index(
        "ix_schedule_pipelines_pipeline_id", "schedule_pipelines", ["pipeline_id"]
    )

    # Backfill: every existing pipeline schedule becomes an attachment to its target.
    op.execute(
        """
        INSERT INTO schedule_pipelines (schedule_id, pipeline_id, tenant_id)
        SELECT id, target_id, tenant_id
        FROM schedules
        WHERE target_kind = 'pipeline'
        """
    )


def downgrade() -> None:
    op.drop_index("ix_schedule_pipelines_pipeline_id", table_name="schedule_pipelines")
    op.drop_index("ix_schedule_pipelines_tenant_id", table_name="schedule_pipelines")
    op.drop_table("schedule_pipelines")
