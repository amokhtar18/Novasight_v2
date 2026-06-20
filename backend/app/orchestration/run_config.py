"""The run-config contract between the backend launcher and the Dagster code location.

Both sides must agree on the generic job names, their op names, and the shape of
``runConfigData`` carried in a launch. These pure helpers are the single source of
that contract on the backend; the ``novasight_orchestration`` code location mirrors
the same names (it cannot import the backend package — separate deployable).

A run is parametrised by *which* registry definition to execute (its id) and the
tenant slug, so one generic job materialises any pipeline / transform job by id —
no per-definition Dagster object or reload is needed to run something new.
"""
from __future__ import annotations

import uuid
from typing import Any

# Generic jobs + their single op (the body is filled in by the ETL/dbt tasks).
PIPELINE_JOB = "pipeline_job"
PIPELINE_OP = "run_pipeline"
TRANSFORM_JOB = "transform_job"
TRANSFORM_OP = "run_transform"
CATALOG_JOB = "catalog_job"
CATALOG_OP = "run_catalog"


def pipeline_run_config(pipeline_id: uuid.UUID | str, tenant: str) -> dict[str, Any]:
    """Dagster ``runConfigData`` to run one pipeline by id, scoped to a tenant."""
    return {
        "ops": {
            PIPELINE_OP: {"config": {"pipeline_id": str(pipeline_id), "tenant": tenant}}
        }
    }


def transform_run_config(transform_job_id: uuid.UUID | str, tenant: str) -> dict[str, Any]:
    """Dagster ``runConfigData`` to run one transform (dbt) job by id, per tenant."""
    return {
        "ops": {
            TRANSFORM_OP: {
                "config": {"transform_job_id": str(transform_job_id), "tenant": tenant}
            }
        }
    }


def catalog_run_config(tenant: str) -> dict[str, Any]:
    """Dagster ``runConfigData`` to catalog one tenant into OpenMetadata.

    Parametrised only by the tenant slug; the code location resolves that tenant's
    ClickHouse DB / Iceberg namespace from the registry (golden rule 2).
    """
    return {"ops": {CATALOG_OP: {"config": {"tenant": tenant}}}}
