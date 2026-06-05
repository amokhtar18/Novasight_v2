"""Catalog & lineage ingestion into OpenMetadata (Phase 5.3, asset).

This is the final observability hop: after the pipeline has built the tenant's
tables (raw → staging → intermediate → mart → serving), this asset pushes their
metadata and end-to-end lineage into OpenMetadata so users can browse a catalog.

## How end-to-end lineage is produced

Two OpenMetadata ingestion stages, both built entirely from settings:

1. **ClickHouse metadata** — registers the tenant's physical tables (the dlt-built
   raw table and the serving table) under the configured OM service, scoped to the
   tenant's ClickHouse database via a schema filter (golden rule 2).
2. **dbt** — reads the dbt ``manifest.json`` (and ``catalog.json`` / ``run_results.json``
   when present) to register every dbt model and the model→model lineage
   (staging → intermediate → mart). OpenMetadata stitches the dbt lineage onto the
   physical tables from stage 1, yielding the full raw → … → serving graph.

## Configuration & tenancy

Every infra value comes from ``OrchestrationSettings`` (golden rule 1): the OM server
URL + JWT and the ClickHouse connection are read from the environment, never literals.
Ingestion is scoped to the tenant's ClickHouse database (``settings.dbt_schema``),
resolved at the boundary — golden rule 2.

## Testability

The config builders are pure (no I/O) and the workflow execution is injected
(``run_catalog_ingestion(..., ingest=...)``), mirroring ``serving.py``'s ``connect``
seam — so the whole unit is testable with a fake ingestor and no live OM server.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from dagster import AssetKey, MaterializeResult, MetadataValue, asset

from .dbt_resource import dbt_project
from .serving import SERVING_ASSET_KEY
from .settings import OrchestrationSettings, get_settings

CATALOG_ASSET_KEY = AssetKey(["catalog_metadata"])

# Stage labels (also the order they run in).
STAGE_CLICKHOUSE = "clickhouse_metadata"
STAGE_DBT = "dbt"


class CatalogIngestor(Protocol):
    """Runs one OpenMetadata ingestion workflow given its config dict."""

    def __call__(self, config: dict[str, Any]) -> None: ...


@dataclass(frozen=True)
class CatalogResult:
    """Outcome of a catalog ingestion run."""

    service_name: str
    scoped_database: str
    stages: list[str]


def _server_config(settings: OrchestrationSettings) -> dict[str, Any]:
    """The OpenMetadata server connection block shared by every workflow."""
    cat = settings.catalog
    return {
        "hostPort": cat.host_port,
        "authProvider": "openmetadata",
        "securityConfig": {"jwtToken": cat.jwt_token.get_secret_value()},
    }


def build_clickhouse_metadata_config(settings: OrchestrationSettings) -> dict[str, Any]:
    """Build the OM workflow that ingests the tenant's ClickHouse tables.

    Scoped to the tenant's ClickHouse database via ``schemaFilterPattern`` so the
    catalog only ever sees this tenant's tables (golden rule 2).
    """
    ch = settings.clickhouse
    cat = settings.catalog
    return {
        "source": {
            "type": "clickhouse",
            "serviceName": cat.service_name,
            "serviceConnection": {
                "config": {
                    "type": "Clickhouse",
                    "scheme": "clickhouse+http",
                    "hostPort": f"{ch.host}:{ch.port}",
                    "username": ch.user,
                    "password": ch.password.get_secret_value(),
                }
            },
            "sourceConfig": {
                "config": {
                    "type": "DatabaseMetadata",
                    "includeViews": True,
                    # Restrict ingestion to the tenant's own ClickHouse database.
                    "schemaFilterPattern": {"includes": [settings.dbt_schema]},
                }
            },
        },
        "sink": {"type": "metadata-rest", "config": {}},
        "workflowConfig": {"openMetadataServerConfig": _server_config(settings)},
    }


def build_dbt_ingestion_config(
    settings: OrchestrationSettings, manifest_path: Path | str
) -> dict[str, Any]:
    """Build the OM workflow that ingests dbt models + lineage from the manifest.

    ``catalog.json`` and ``run_results.json`` (siblings of the manifest) are included
    when present, enabling column-level lineage and test/result metadata.
    """
    cat = settings.catalog
    manifest = Path(manifest_path)
    dbt_config_source: dict[str, Any] = {
        "dbtConfigType": "local",
        "dbtManifestFilePath": str(manifest),
    }
    catalog_file = manifest.with_name("catalog.json")
    run_results = manifest.with_name("run_results.json")
    if catalog_file.exists():
        dbt_config_source["dbtCatalogFilePath"] = str(catalog_file)
    if run_results.exists():
        dbt_config_source["dbtRunResultsFilePath"] = str(run_results)

    return {
        "source": {
            "type": "dbt",
            "serviceName": cat.service_name,
            "sourceConfig": {
                "config": {
                    "type": "DBT",
                    "dbtConfigSource": dbt_config_source,
                }
            },
        },
        "sink": {"type": "metadata-rest", "config": {}},
        "workflowConfig": {"openMetadataServerConfig": _server_config(settings)},
    }


def _run_workflow(config: dict[str, Any]) -> None:
    """Execute one OpenMetadata ingestion workflow (thin glue, lazily imported).

    The OpenMetadata ingestion SDK is an optional dependency (the ``catalog`` extra),
    imported here so the rest of the code location — and its tests — don't require it.
    """
    from metadata.workflow.metadata import MetadataWorkflow

    workflow = MetadataWorkflow.create(config)
    workflow.execute()
    workflow.raise_from_status()
    workflow.print_status()
    workflow.stop()


def run_catalog_ingestion(
    settings: OrchestrationSettings,
    manifest_path: Path | str,
    *,
    ingest: CatalogIngestor = _run_workflow,
) -> CatalogResult:
    """Run both ingestion stages (ClickHouse metadata, then dbt) and report what ran.

    ``ingest`` is injected so tests drive the full unit with a fake and no live OM
    server. dbt runs after the ClickHouse metadata so its model→model lineage attaches
    to tables that already exist in the catalog.
    """
    ingest(build_clickhouse_metadata_config(settings))
    ingest(build_dbt_ingestion_config(settings, manifest_path))
    return CatalogResult(
        service_name=settings.catalog.service_name,
        scoped_database=settings.dbt_schema,
        stages=[STAGE_CLICKHOUSE, STAGE_DBT],
    )


@asset(
    key=CATALOG_ASSET_KEY,
    deps=[SERVING_ASSET_KEY],
    group_name="catalog",
    compute_kind="openmetadata",
    description=(
        "Ingests the tenant's ClickHouse tables and dbt models + lineage into "
        "OpenMetadata so datasets and end-to-end (raw → staging → mart → serving) "
        "lineage are browsable. Downstream of serving so every table exists; "
        "tenant-scoped to the tenant's ClickHouse database."
    ),
)
def catalog_metadata() -> MaterializeResult:
    """Materialize the catalog: push table metadata + dbt lineage to OpenMetadata."""
    settings = get_settings()
    result = run_catalog_ingestion(settings, dbt_project.manifest_path)
    return MaterializeResult(
        metadata={
            "catalog_service": MetadataValue.text(result.service_name),
            "openmetadata_host": MetadataValue.text(settings.catalog.host_port),
            "scoped_database": MetadataValue.text(result.scoped_database),
            "stages": MetadataValue.text(", ".join(result.stages)),
        }
    )
