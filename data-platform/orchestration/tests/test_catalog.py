"""Tests for the catalog/lineage ingestion (``catalog.py``).

Exercised without a live OpenMetadata server, in the same style as the serving
tests: the config builders are pure, and the workflow run is injected, so we assert
on the configs produced. We verify three things the task calls for:

* **datasets** — the ClickHouse metadata stage registers the tenant's tables;
* **end-to-end lineage** — the dbt stage points at the manifest (raw → … → mart);
* **env-driven + tenant-scoped** — every value comes from settings, and ingestion is
  restricted to the tenant's own ClickHouse database (no cross-tenant bleed).
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from novasight_orchestration.catalog import (
    STAGE_CLICKHOUSE,
    STAGE_DBT,
    build_clickhouse_metadata_config,
    build_dbt_ingestion_config,
    run_catalog_ingestion,
)


def _secret(value: str) -> Any:
    return SimpleNamespace(get_secret_value=lambda: value)


def _settings(
    *,
    dbt_schema: str = "tenant_local",
    service_name: str = "novasight_clickhouse",
    host_port: str = "http://openmetadata:8585/api",
) -> Any:
    """Minimal OrchestrationSettings stand-in (only the fields the builders read)."""
    return SimpleNamespace(
        dbt_schema=dbt_schema,
        clickhouse=SimpleNamespace(
            host="clickhouse", port=8123, user="default", password=_secret("chpw")
        ),
        catalog=SimpleNamespace(
            host_port=host_port, service_name=service_name, jwt_token=_secret("jwt-tok")
        ),
    )


def _manifest(tmp_path: Path, *, siblings: bool = False) -> Path:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"nodes": {}}), encoding="utf-8")
    if siblings:
        (tmp_path / "catalog.json").write_text("{}", encoding="utf-8")
        (tmp_path / "run_results.json").write_text("{}", encoding="utf-8")
    return manifest


# --- ClickHouse metadata config: datasets, env-driven, tenant-scoped --------------


def test_clickhouse_config_is_env_driven() -> None:
    cfg = build_clickhouse_metadata_config(_settings())

    assert cfg["source"]["type"] == "clickhouse"
    assert cfg["source"]["serviceName"] == "novasight_clickhouse"

    conn = cfg["source"]["serviceConnection"]["config"]
    assert conn["hostPort"] == "clickhouse:8123"
    assert conn["username"] == "default"
    assert conn["password"] == "chpw"

    server = cfg["workflowConfig"]["openMetadataServerConfig"]
    assert server["hostPort"] == "http://openmetadata:8585/api"
    assert server["securityConfig"]["jwtToken"] == "jwt-tok"


def test_clickhouse_config_scopes_to_own_tenant_database() -> None:
    a = build_clickhouse_metadata_config(_settings(dbt_schema="tenant_a"))
    b = build_clickhouse_metadata_config(_settings(dbt_schema="tenant_b"))

    assert a["source"]["sourceConfig"]["config"]["schemaFilterPattern"]["includes"] == [
        "tenant_a"
    ]
    assert b["source"]["sourceConfig"]["config"]["schemaFilterPattern"]["includes"] == [
        "tenant_b"
    ]
    # No cross-tenant bleed in either rendered config.
    assert "tenant_b" not in json.dumps(a)
    assert "tenant_a" not in json.dumps(b)


# --- dbt config: end-to-end lineage from the manifest -----------------------------


def test_dbt_config_points_at_manifest(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    cfg = build_dbt_ingestion_config(_settings(), manifest)

    assert cfg["source"]["type"] == "dbt"
    assert cfg["source"]["serviceName"] == "novasight_clickhouse"
    src = cfg["source"]["sourceConfig"]["config"]["dbtConfigSource"]
    assert src["dbtManifestFilePath"] == str(manifest)
    # No siblings present → only the manifest is referenced.
    assert "dbtCatalogFilePath" not in src
    assert "dbtRunResultsFilePath" not in src
    # The OM server connection is carried here too.
    assert cfg["workflowConfig"]["openMetadataServerConfig"]["hostPort"].endswith("/api")


def test_dbt_config_includes_sibling_catalog_and_run_results(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, siblings=True)
    src = build_dbt_ingestion_config(_settings(), manifest)["source"]["sourceConfig"][
        "config"
    ]["dbtConfigSource"]

    assert src["dbtCatalogFilePath"] == str(tmp_path / "catalog.json")
    assert src["dbtRunResultsFilePath"] == str(tmp_path / "run_results.json")


# --- run_catalog_ingestion: both stages, injected workflow ------------------------


def test_run_catalog_ingestion_runs_both_stages(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    captured: list[dict[str, Any]] = []

    result = run_catalog_ingestion(_settings(), manifest, ingest=captured.append)

    # Datasets first (ClickHouse tables), then lineage (dbt models).
    assert [c["source"]["type"] for c in captured] == ["clickhouse", "dbt"]
    assert result.stages == [STAGE_CLICKHOUSE, STAGE_DBT]
    assert result.service_name == "novasight_clickhouse"
    assert result.scoped_database == "tenant_local"


def test_run_catalog_ingestion_is_tenant_scoped(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    captured: list[dict[str, Any]] = []

    run_catalog_ingestion(_settings(dbt_schema="acme"), manifest, ingest=captured.append)

    metadata_cfg = captured[0]
    assert metadata_cfg["source"]["sourceConfig"]["config"]["schemaFilterPattern"][
        "includes"
    ] == ["acme"]
    # The whole rendered metadata stage is scoped to this tenant only.
    assert "tenant_local" not in json.dumps(metadata_cfg)
