"""The Dagster code location: assets + resources wired together.

Loaded by ``dagster dev`` via ``[tool.dagster] module_name`` in ``pyproject.toml``.

Asset graph (lineage shown in the Dagster UI):

    regional_sales_raw            (dlt ingestion -> tenant ClickHouse DB)
        -> stg_phase1__regional_sales      (dbt, view)
        -> int_regional_sales_enriched     (dbt, ephemeral)
        -> mart_regional_sales             (dbt, table; validated by the quality gate)
        -> mart_regional_sales_serving     (loads the validated mart -> tenant serving table)
        -> catalog_metadata                (ingests tables + dbt lineage into OpenMetadata)

dbt tests are surfaced as asset checks (``dbt build`` in ``dbt_assets.py``); the serving
asset adds a post-load integrity check (``serving.py``); the catalog asset publishes the
end-to-end lineage to OpenMetadata (``catalog.py``).

Beyond this static asset graph, the location is also *generic and registry-driven*
(``dynamic.py`` + ``registry.py``): two generic jobs run any tenant's pipeline or
transform by id, and a schedule is built for every row in the ``schedules`` table.
The schedule read is best-effort — if the control-plane database is unreachable the
location still loads with its jobs and assets (it just has no dynamic schedules yet).
"""
from __future__ import annotations

import logging

from dagster import Definitions, ScheduleDefinition
from dagster_dbt import DbtCliResource

from .catalog import catalog_metadata
from .dbt_assets import novasight_dbt_assets
from .dbt_resource import dbt_project
from .dynamic import build_schedules, pipeline_job, transform_job
from .ingestion import regional_sales_raw
from .registry import load_schedule_rows
from .serving import mart_regional_sales_serving

logger = logging.getLogger(__name__)


def _load_dynamic_schedules() -> list[ScheduleDefinition]:
    """Build schedules from the registry, tolerating an unreachable database.

    The code location must always import (so its jobs/assets are available even before
    the control plane is up); a failed read degrades to "no dynamic schedules yet"
    rather than breaking the whole location.
    """
    try:
        return build_schedules(load_schedule_rows())
    except Exception as exc:  # noqa: BLE001 — defensive: any DB/driver error degrades gracefully
        logger.warning("dynamic schedules unavailable (registry read failed): %s", exc)
        return []


defs = Definitions(
    assets=[
        regional_sales_raw,
        novasight_dbt_assets,
        mart_regional_sales_serving,
        catalog_metadata,
    ],
    # Generic jobs run any pipeline/transform by id (see dynamic.py); the backend
    # launches them via the GraphQL client with the run-config contract.
    jobs=[pipeline_job, transform_job],
    schedules=_load_dynamic_schedules(),
    resources={
        # The dbt CLI inherits the Dagster process environment, so the env-driven
        # profiles.yml (CLICKHOUSE__*, DBT_SCHEMA, DBT_PHASE1_DATASET_TABLE) resolves
        # exactly as it does for a direct `dbt build`.
        "dbt": DbtCliResource(project_dir=dbt_project),
    },
)
