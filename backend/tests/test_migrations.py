"""Proves `alembic upgrade head` builds the control-plane schema.

Runs the real migration against a throwaway SQLite database through Alembic's
command API (env.py honours a ``sqlalchemy.url`` injected on the Config, so no
Postgres is needed). This is the automated form of the Task 0.4 acceptance
criterion. The test is synchronous because env.py drives its own asyncio loop.
"""
from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command

_ALEMBIC_DIR = Path(__file__).resolve().parents[1] / "alembic"


def _make_config(db_path: Path) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(_ALEMBIC_DIR))
    # Injected url wins over settings in env.py — keeps the test infra-free.
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
    return cfg


def test_upgrade_head_builds_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "control_plane.db"
    cfg = _make_config(db_path)

    command.upgrade(cfg, "head")

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert {
            "tenants",
            "tenant_resource_maps",
            "users",
            "datasets",
            "report_definitions",
            "kpi_thresholds",
            # Phase 1 definition registry (0007).
            "source_connections",
            "pipelines",
            "pipeline_runs",
            "dbt_models",
            "dbt_tests",
            "transform_jobs",
            "semantic_models",
            "charts",
            "dashboards",
            "dashboard_tiles",
            "schedules",
        } <= tables
        # The migration was actually stamped.
        assert "alembic_version" in tables

        # Spot-check the new users auth columns landed (0006).
        user_cols = {c["name"] for c in inspector.get_columns("users")}
        assert {"name", "password_hash", "roles"} <= user_cols

        report_cols = {c["name"] for c in inspector.get_columns("report_definitions")}
        assert {
            "tenant_id",
            "dataset_id",
            "query_spec",
            "schedule",
            "recipients",
            "enabled",
        } <= report_cols

        cols = {c["name"] for c in inspector.get_columns("tenant_resource_maps")}
        assert {"iceberg_namespace", "clickhouse_db", "dbt_schema"} <= cols

        dataset_cols = {c["name"] for c in inspector.get_columns("datasets")}
        assert {
            "tenant_id",
            "object_key",
            "size_bytes",
            "status",
            "sensitive_columns",
        } <= dataset_cols
    finally:
        engine.dispose()


def test_downgrade_base_drops_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "control_plane.db"
    cfg = _make_config(db_path)

    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        tables = set(inspect(engine).get_table_names())
        assert "tenants" not in tables
        assert "users" not in tables
        assert "tenant_resource_maps" not in tables
        assert "datasets" not in tables
        assert "report_definitions" not in tables
        assert "kpi_thresholds" not in tables
        # Registry tables are gone too.
        assert "pipelines" not in tables
        assert "charts" not in tables
        assert "dashboard_tiles" not in tables
        assert "schedules" not in tables
    finally:
        engine.dispose()
