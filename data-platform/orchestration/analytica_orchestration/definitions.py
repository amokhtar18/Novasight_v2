"""The Dagster code location: assets + resources wired together.

Loaded by ``dagster dev`` via ``[tool.dagster] module_name`` in ``pyproject.toml``.

Asset graph (lineage shown in the Dagster UI):

    regional_sales_raw            (dlt ingestion -> tenant ClickHouse DB)
        -> stg_phase1__regional_sales      (dbt, view)
        -> int_regional_sales_enriched     (dbt, ephemeral)
        -> mart_regional_sales             (dbt, table; validated by the quality gate)
        -> mart_regional_sales_serving     (loads the validated mart -> tenant serving table)

dbt tests are surfaced as asset checks (``dbt build`` in ``dbt_assets.py``); the serving
asset adds a post-load integrity check (``serving.py``).
"""
from __future__ import annotations

from dagster import Definitions
from dagster_dbt import DbtCliResource

from .dbt_assets import analytica_dbt_assets
from .dbt_resource import dbt_project
from .ingestion import regional_sales_raw
from .serving import mart_regional_sales_serving

defs = Definitions(
    assets=[regional_sales_raw, analytica_dbt_assets, mart_regional_sales_serving],
    resources={
        # The dbt CLI inherits the Dagster process environment, so the env-driven
        # profiles.yml (CLICKHOUSE__*, DBT_SCHEMA, DBT_PHASE1_DATASET_TABLE) resolves
        # exactly as it does for a direct `dbt build`.
        "dbt": DbtCliResource(project_dir=dbt_project),
    },
)
