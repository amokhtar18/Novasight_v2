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

import json
import logging
import os
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from dagster import AssetKey, MaterializeResult, MetadataValue, asset

from .dbt_resource import dbt_project
from .serving import SERVING_ASSET_KEY
from .settings import OrchestrationSettings, get_settings

logger = logging.getLogger(__name__)

# The standalone OM-SDK runner (executed by the isolated /opt/om-venv Python).
_OM_RUNNER = Path(__file__).with_name("catalog_om_runner.py")

CATALOG_ASSET_KEY = AssetKey(["catalog_metadata"])

# Stage labels (also the order they run in).
STAGE_CLICKHOUSE = "clickhouse_metadata"
STAGE_ICEBERG = "iceberg_metadata"
STAGE_DBT = "dbt"


class CatalogIngestor(Protocol):
    """Runs one OpenMetadata ingestion workflow given its config dict."""

    def __call__(self, config: dict[str, Any]) -> None: ...


@dataclass(frozen=True)
class CatalogScope:
    """The tenant data surfaces a catalog run is restricted to (golden rule 2).

    Resolved at the boundary (from the tenant's resource map, or the single-tenant
    ``DBT_SCHEMA`` on-prem) and threaded into every ingestion stage, so a run only
    ever sees one tenant's tables — never inferred later or widened.
    """

    clickhouse_db: str                 # tenant's ClickHouse database == dbt schema
    iceberg_namespace: str | None = None  # tenant's Iceberg namespace (lake metadata stage)
    tenant: str | None = None          # tenant slug — set on the registry-driven path,
    #                                    enables the cross-system lineage stage (catalog_lineage)


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


def build_clickhouse_metadata_config(
    settings: OrchestrationSettings, scope: CatalogScope
) -> dict[str, Any]:
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
                    "schemaFilterPattern": {"includes": [scope.clickhouse_db]},
                }
            },
        },
        "sink": {"type": "metadata-rest", "config": {}},
        "workflowConfig": {"openMetadataServerConfig": _server_config(settings)},
    }


def build_iceberg_metadata_config(
    settings: OrchestrationSettings, scope: CatalogScope
) -> dict[str, Any]:
    """Build the OM workflow that ingests the tenant's Iceberg (lake) tables.

    Registers the landing tables one hop upstream of ClickHouse, scoped to the tenant's
    Iceberg namespace via ``schemaFilterPattern`` (golden rule 2). The REST catalog URI
    / warehouse / token all come from the same ``ICEBERG__*`` env the backend writer
    uses (golden rule 1). Only meaningful when the scope carries a namespace.
    """
    ice = settings.iceberg
    cat = settings.catalog
    namespace = scope.iceberg_namespace or ""
    # OM's RestCatalogConnection accepts only {uri, credential, token, ssl, sigv4,
    # fileSystem}; the warehouse is ``warehouseLocation`` on the IcebergCatalog (sibling
    # of ``connection``), not inside the connection.
    rest_connection: dict[str, Any] = {"uri": ice.catalog_uri}
    if ice.catalog_token is not None:
        rest_connection["token"] = ice.catalog_token.get_secret_value()
    return {
        "source": {
            "type": "iceberg",
            "serviceName": cat.iceberg_service_name,
            "serviceConnection": {
                "config": {
                    "type": "Iceberg",
                    "catalog": {
                        "name": cat.iceberg_service_name,
                        "connection": rest_connection,
                        "warehouseLocation": ice.warehouse,
                    },
                }
            },
            "sourceConfig": {
                "config": {
                    "type": "DatabaseMetadata",
                    # Restrict ingestion to the tenant's own Iceberg namespace.
                    "schemaFilterPattern": {"includes": [namespace]},
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


def run_om_runner(
    mode: str,
    payload: dict[str, Any],
    *,
    python: str,
    runner: Path = _OM_RUNNER,
    run: Callable[..., Any] = subprocess.run,
) -> None:
    """Hand one payload to the isolated OM-SDK runner via the dedicated venv's Python.

    The OM ingestion SDK can't share the dagster/dbt venv, so it lives in ``python``'s
    venv and we invoke ``catalog_om_runner.py`` (``mode`` = ``workflow`` | ``lineage``)
    with the payload serialised to a temp JSON file. ``run`` is injected so the argv +
    serialisation are unit-testable without a subprocess. Raises on a non-zero exit.
    """
    fd, path = tempfile.mkstemp(suffix=".json", prefix="om_catalog_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        argv: Sequence[str] = [python, str(runner), mode, path]
        run(argv, check=True)
    finally:
        os.unlink(path)


def _run_workflow(config: dict[str, Any]) -> None:
    """Run one OpenMetadata ingestion workflow in the isolated OM-SDK venv (subprocess)."""
    run_om_runner("workflow", config, python=get_settings().catalog.runner_python)


def run_catalog_ingestion(
    settings: OrchestrationSettings,
    manifest_path: Path | str,
    scope: CatalogScope,
    *,
    ingest: CatalogIngestor = _run_workflow,
) -> CatalogResult:
    """Run both ingestion stages (ClickHouse metadata, then dbt) and report what ran.

    ``scope`` restricts every stage to one tenant's data surfaces (golden rule 2).
    ``ingest`` is injected so tests drive the full unit with a fake and no live OM
    server. The Iceberg (lake) stage runs only when the scope carries a namespace —
    the single-tenant static asset has none, while the registry-driven job does — and
    is **best-effort**: OpenMetadata's Iceberg connector is immature, and the lake
    tables are also created (and linked) by the cross-system lineage stage, so a scan
    failure must not abort the run. dbt runs last so its model→model lineage attaches
    to tables that already exist.
    """
    stages = [STAGE_CLICKHOUSE]
    ingest(build_clickhouse_metadata_config(settings, scope))
    if scope.iceberg_namespace:
        try:
            ingest(build_iceberg_metadata_config(settings, scope))
            stages.append(STAGE_ICEBERG)
        except Exception as exc:  # noqa: BLE001 — best-effort enrichment; lineage still adds the hop
            logger.warning("iceberg metadata stage skipped (connector error): %s", exc)
    ingest(build_dbt_ingestion_config(settings, manifest_path))
    stages.append(STAGE_DBT)
    return CatalogResult(
        service_name=settings.catalog.service_name,
        scoped_database=scope.clickhouse_db,
        stages=stages,
    )


def run_catalog_for_scope(
    scope: CatalogScope, *, ingest: CatalogIngestor = _run_workflow
) -> CatalogResult:
    """Catalog one tenant from an explicit scope — the per-tenant ``catalog_job`` entry.

    Runs the per-table ingestion stages, then — on the registry-driven path (when the
    scope carries a tenant slug) — stitches the cross-system ``source → Iceberg →
    ClickHouse → Cube`` lineage from that tenant's own registry rows. Wires the process
    settings + shared dbt manifest so ``dynamic.py`` stays free of the dbt-project
    import; ``ingest`` stays injectable for tests. Scope is resolved by the caller from
    the registry (golden rule 2).
    """
    settings = get_settings()
    result = run_catalog_ingestion(settings, dbt_project.manifest_path, scope, ingest=ingest)
    if scope.tenant:
        # Lazy imports: ``catalog_lineage`` depends on this module's ``CatalogScope``,
        # and the registry read only happens on the live (stack) path.
        from .catalog_lineage import run_lineage
        from .registry import load_pipelines_for_tenant, load_semantic_models_for_tenant

        run_lineage(
            settings,
            scope,
            load_pipelines_for_tenant(scope.tenant),
            load_semantic_models_for_tenant(scope.tenant),
        )
    return result


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
    """Materialize the catalog: push table metadata + dbt lineage to OpenMetadata.

    The single static asset scopes itself to the boundary tenant (the ``DBT_SCHEMA``
    resolved on-prem); the per-tenant ``catalog_job`` (``dynamic.py``) catalogs every
    other tenant from its registry-resolved scope.
    """
    settings = get_settings()
    scope = CatalogScope(clickhouse_db=settings.dbt_schema)
    result = run_catalog_ingestion(settings, dbt_project.manifest_path, scope)
    return MaterializeResult(
        metadata={
            "catalog_service": MetadataValue.text(result.service_name),
            "openmetadata_host": MetadataValue.text(settings.catalog.host_port),
            "scoped_database": MetadataValue.text(result.scoped_database),
            "stages": MetadataValue.text(", ".join(result.stages)),
        }
    )
