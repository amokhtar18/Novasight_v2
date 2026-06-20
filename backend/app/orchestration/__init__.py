"""Backend↔Dagster control plane.

Lets the API launch runs and manage the dynamic code location over Dagster's
GraphQL API, so a tenant superuser runs/schedules pipelines and dbt jobs without
opening Dagster. Schedules are owned by the registry (Postgres) and built into the
``novasight_orchestration`` code location declaratively; toggling one is a registry
update + a code-location reload (no brittle start/stop mutations).
"""
from __future__ import annotations

from app.orchestration.dagster_client import (
    DagsterClient,
    DagsterError,
    get_dagster_client,
)
from app.orchestration.run_config import (
    CATALOG_JOB,
    CATALOG_OP,
    PIPELINE_JOB,
    PIPELINE_OP,
    TRANSFORM_JOB,
    TRANSFORM_OP,
    catalog_run_config,
    pipeline_run_config,
    transform_run_config,
)

__all__ = [
    "CATALOG_JOB",
    "CATALOG_OP",
    "PIPELINE_JOB",
    "PIPELINE_OP",
    "TRANSFORM_JOB",
    "TRANSFORM_OP",
    "DagsterClient",
    "DagsterError",
    "catalog_run_config",
    "get_dagster_client",
    "pipeline_run_config",
    "transform_run_config",
]
