"""definition registry: sources, pipelines, dbt, semantic, charts, dashboards, schedules

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-06

Creates the per-tenant definition registry that backs the self-service product:
ETL source connections + pipelines (+ runs), dbt models + tests, transform jobs,
semantic models, saved charts, dashboards (+ tiles), and schedules. Every table is
tenant-scoped (``tenant_id`` FK + index). Mirrors the ``app.models.*`` classes;
names follow the metadata naming convention so downgrade is reversible.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def _tenant_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id"], ["tenants.id"],
        name=op.f(f"fk_{table}_tenant_id_tenants"), ondelete="CASCADE",
    )


def upgrade() -> None:
    # --- source_connections ---
    op.create_table(
        "source_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("secret_ciphertext", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        *_timestamps(),
        _tenant_fk("source_connections"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_connections")),
    )
    op.create_index(
        op.f("ix_source_connections_tenant_id"), "source_connections", ["tenant_id"], unique=False
    )

    # --- pipelines ---
    op.create_table(
        "pipelines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("source_connection_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("target_table", sa.String(length=255), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        *_timestamps(),
        _tenant_fk("pipelines"),
        sa.ForeignKeyConstraint(
            ["source_connection_id"], ["source_connections.id"],
            name=op.f("fk_pipelines_source_connection_id_source_connections"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pipelines")),
    )
    op.create_index(op.f("ix_pipelines_tenant_id"), "pipelines", ["tenant_id"], unique=False)

    # --- pipeline_runs ---
    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("pipeline_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="queued", nullable=False),
        sa.Column("dagster_run_id", sa.String(length=64), nullable=True),
        sa.Column("rows", sa.BigInteger(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        *_timestamps(),
        _tenant_fk("pipeline_runs"),
        sa.ForeignKeyConstraint(
            ["pipeline_id"], ["pipelines.id"],
            name=op.f("fk_pipeline_runs_pipeline_id_pipelines"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pipeline_runs")),
    )
    op.create_index(op.f("ix_pipeline_runs_tenant_id"), "pipeline_runs", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_pipeline_runs_pipeline_id"), "pipeline_runs", ["pipeline_id"], unique=False)

    # --- dbt_models ---
    op.create_table(
        "dbt_models",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("layer", sa.String(length=32), server_default="marts", nullable=False),
        sa.Column("materialization", sa.String(length=32), server_default="table", nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("sql", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        *_timestamps(),
        _tenant_fk("dbt_models"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dbt_models")),
    )
    op.create_index(op.f("ix_dbt_models_tenant_id"), "dbt_models", ["tenant_id"], unique=False)

    # --- dbt_tests ---
    op.create_table(
        "dbt_tests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("dbt_model_id", sa.Uuid(), nullable=False),
        sa.Column("column_name", sa.String(length=255), nullable=True),
        sa.Column("test_type", sa.String(length=64), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        *_timestamps(),
        _tenant_fk("dbt_tests"),
        sa.ForeignKeyConstraint(
            ["dbt_model_id"], ["dbt_models.id"],
            name=op.f("fk_dbt_tests_dbt_model_id_dbt_models"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dbt_tests")),
    )
    op.create_index(op.f("ix_dbt_tests_tenant_id"), "dbt_tests", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_dbt_tests_dbt_model_id"), "dbt_tests", ["dbt_model_id"], unique=False)

    # --- transform_jobs ---
    op.create_table(
        "transform_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("selection", sa.String(length=512), server_default="", nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        *_timestamps(),
        _tenant_fk("transform_jobs"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transform_jobs")),
    )
    op.create_index(op.f("ix_transform_jobs_tenant_id"), "transform_jobs", ["tenant_id"], unique=False)

    # --- semantic_models ---
    op.create_table(
        "semantic_models",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("base_table", sa.String(length=255), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        *_timestamps(),
        _tenant_fk("semantic_models"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_semantic_models")),
    )
    op.create_index(op.f("ix_semantic_models_tenant_id"), "semantic_models", ["tenant_id"], unique=False)

    # --- charts ---
    op.create_table(
        "charts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("spec", sa.JSON(), nullable=False),
        sa.Column("source_kind", sa.String(length=32), server_default="semantic", nullable=False),
        sa.Column("source_ref", sa.String(length=64), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        *_timestamps(),
        _tenant_fk("charts"),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_charts_owner_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_charts")),
    )
    op.create_index(op.f("ix_charts_tenant_id"), "charts", ["tenant_id"], unique=False)

    # --- dashboards ---
    op.create_table(
        "dashboards",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        *_timestamps(),
        _tenant_fk("dashboards"),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_dashboards_owner_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dashboards")),
    )
    op.create_index(op.f("ix_dashboards_tenant_id"), "dashboards", ["tenant_id"], unique=False)

    # --- dashboard_tiles ---
    op.create_table(
        "dashboard_tiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("dashboard_id", sa.Uuid(), nullable=False),
        sa.Column("chart_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("x", sa.Integer(), server_default="0", nullable=False),
        sa.Column("y", sa.Integer(), server_default="0", nullable=False),
        sa.Column("w", sa.Integer(), server_default="6", nullable=False),
        sa.Column("h", sa.Integer(), server_default="4", nullable=False),
        *_timestamps(),
        _tenant_fk("dashboard_tiles"),
        sa.ForeignKeyConstraint(
            ["dashboard_id"], ["dashboards.id"],
            name=op.f("fk_dashboard_tiles_dashboard_id_dashboards"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chart_id"], ["charts.id"],
            name=op.f("fk_dashboard_tiles_chart_id_charts"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dashboard_tiles")),
    )
    op.create_index(op.f("ix_dashboard_tiles_tenant_id"), "dashboard_tiles", ["tenant_id"], unique=False)
    op.create_index(
        op.f("ix_dashboard_tiles_dashboard_id"), "dashboard_tiles", ["dashboard_id"], unique=False
    )

    # --- schedules ---
    op.create_table(
        "schedules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("target_kind", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("cron", sa.String(length=128), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("dagster_schedule_name", sa.String(length=255), nullable=True),
        *_timestamps(),
        _tenant_fk("schedules"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_schedules")),
    )
    op.create_index(op.f("ix_schedules_tenant_id"), "schedules", ["tenant_id"], unique=False)


def downgrade() -> None:
    for table in (
        "schedules",
        "dashboard_tiles",
        "dashboards",
        "charts",
        "semantic_models",
        "transform_jobs",
        "dbt_tests",
        "dbt_models",
        "pipeline_runs",
        "pipelines",
        "source_connections",
    ):
        op.drop_table(table)
