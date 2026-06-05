"""The Analytica dbt project, exposed to Dagster.

``DbtProject`` points at the existing ``data-platform/dbt`` project (no copy, one
source of truth). Its manifest is what ``dagster-dbt`` reads to turn every dbt model
into a software-defined asset and every dbt test into an asset check.

No hosts, credentials, or schemas live here: the dbt connection comes from the
project's env-driven ``profiles.yml`` (golden rule 1). The ClickHouse credentials and
``DBT_SCHEMA`` are passed through from the Dagster process environment when the
``DbtCliResource`` shells out to dbt.
"""
from __future__ import annotations

from pathlib import Path

from dagster_dbt import DbtProject

# data-platform/orchestration/analytica_orchestration/dbt_resource.py
#   parents[2] == data-platform/  ->  the sibling dbt project lives at data-platform/dbt
DBT_PROJECT_DIR = Path(__file__).resolve().parents[2] / "dbt"

dbt_project = DbtProject(
    project_dir=DBT_PROJECT_DIR,
    # profiles.yml lives inside the project dir; it is fully env-driven.
    profiles_dir=DBT_PROJECT_DIR,
)
# In `dagster dev` this regenerates the manifest (runs `dbt parse`) so edits to the
# dbt project show up without a manual build step. In packaged deployments the
# pre-built manifest committed under target/ is used as-is.
dbt_project.prepare_if_dev()
