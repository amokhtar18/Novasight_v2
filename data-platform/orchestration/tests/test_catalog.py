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
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from novasight_orchestration.catalog import (
    _OM_RUNNER,
    STAGE_CLICKHOUSE,
    STAGE_DBT,
    STAGE_ICEBERG,
    CatalogScope,
    build_clickhouse_metadata_config,
    build_dbt_ingestion_config,
    build_iceberg_metadata_config,
    run_catalog_ingestion,
    run_om_runner,
)


def _secret(value: str) -> Any:
    return SimpleNamespace(get_secret_value=lambda: value)


def _settings(
    *,
    service_name: str = "novasight_clickhouse",
    host_port: str = "http://openmetadata:8585/api",
    iceberg_token: str | None = None,
) -> Any:
    """Minimal OrchestrationSettings stand-in (only the fields the builders read)."""
    return SimpleNamespace(
        clickhouse=SimpleNamespace(
            host="clickhouse", port=8123, user="default", password=_secret("chpw")
        ),
        iceberg=SimpleNamespace(
            catalog_uri="http://iceberg-rest:8181",
            warehouse="s3://lake/warehouse",
            catalog_token=_secret(iceberg_token) if iceberg_token else None,
        ),
        catalog=SimpleNamespace(
            host_port=host_port,
            service_name=service_name,
            iceberg_service_name="novasight_iceberg",
            source_service_name="novasight_sources",
            semantic_service_name="novasight_semantic",
            jwt_token=_secret("jwt-tok"),
        ),
    )


def _scope(
    clickhouse_db: str = "tenant_local",
    *,
    iceberg_namespace: str | None = None,
    tenant: str | None = None,
) -> CatalogScope:
    """A tenant catalog scope (what the builders filter ingestion to)."""
    return CatalogScope(
        clickhouse_db=clickhouse_db, iceberg_namespace=iceberg_namespace, tenant=tenant
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
    cfg = build_clickhouse_metadata_config(_settings(), _scope())

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
    a = build_clickhouse_metadata_config(_settings(), _scope("tenant_a"))
    b = build_clickhouse_metadata_config(_settings(), _scope("tenant_b"))

    assert a["source"]["sourceConfig"]["config"]["schemaFilterPattern"]["includes"] == [
        "tenant_a"
    ]
    assert b["source"]["sourceConfig"]["config"]["schemaFilterPattern"]["includes"] == [
        "tenant_b"
    ]
    # No cross-tenant bleed in either rendered config.
    assert "tenant_b" not in json.dumps(a)
    assert "tenant_a" not in json.dumps(b)


# --- Iceberg metadata config: lake datasets, env-driven, tenant-scoped ------------


def test_iceberg_config_is_env_driven_and_scoped() -> None:
    cfg = build_iceberg_metadata_config(_settings(), _scope(iceberg_namespace="ns_acme"))

    assert cfg["source"]["type"] == "iceberg"
    assert cfg["source"]["serviceName"] == "novasight_iceberg"
    catalog = cfg["source"]["serviceConnection"]["config"]["catalog"]
    # The REST connection carries only the uri (+ optional token); the warehouse is the
    # catalog's warehouseLocation (OM's IcebergCatalog schema), not inside the connection.
    assert catalog["connection"] == {"uri": "http://iceberg-rest:8181"}
    assert catalog["warehouseLocation"] == "s3://lake/warehouse"
    # Restricted to the tenant's own Iceberg namespace.
    assert cfg["source"]["sourceConfig"]["config"]["schemaFilterPattern"]["includes"] == [
        "ns_acme"
    ]


def test_iceberg_config_includes_token_when_set() -> None:
    cfg = build_iceberg_metadata_config(
        _settings(iceberg_token="rest-tok"), _scope(iceberg_namespace="ns_acme")
    )
    conn = cfg["source"]["serviceConnection"]["config"]["catalog"]["connection"]
    assert conn["token"] == "rest-tok"


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


# --- run_om_runner: shells out to the isolated OM-SDK venv ------------------------


def test_run_om_runner_invokes_isolated_python_with_payload() -> None:
    seen: dict[str, Any] = {}

    def fake_run(argv: list[str], check: bool) -> None:
        seen["argv"] = list(argv)
        seen["check"] = check
        with open(argv[-1], encoding="utf-8") as fh:
            seen["payload"] = json.load(fh)

    run_om_runner(
        "workflow", {"source": {"type": "clickhouse"}},
        python="/opt/om-venv/bin/python", run=fake_run,
    )

    # Invoked the isolated venv's Python on the standalone runner, in workflow mode.
    assert seen["argv"][:3] == ["/opt/om-venv/bin/python", str(_OM_RUNNER), "workflow"]
    assert seen["check"] is True
    # The payload was handed over as a JSON temp file, then cleaned up afterwards.
    assert seen["payload"] == {"source": {"type": "clickhouse"}}
    assert not os.path.exists(seen["argv"][3])


def test_run_om_runner_cleans_up_temp_file_on_failure() -> None:
    seen: dict[str, Any] = {}

    def boom(argv: list[str], check: bool) -> None:
        seen["path"] = argv[-1]
        raise RuntimeError("runner failed")

    try:
        run_om_runner("lineage", {"edges": []}, python="py", run=boom)
    except RuntimeError:
        pass
    assert not os.path.exists(seen["path"])  # temp file removed even on error


# --- run_catalog_ingestion: both stages, injected workflow ------------------------


def test_run_catalog_ingestion_runs_clickhouse_then_dbt_without_namespace(
    tmp_path: Path,
) -> None:
    manifest = _manifest(tmp_path)
    captured: list[dict[str, Any]] = []

    result = run_catalog_ingestion(_settings(), manifest, _scope(), ingest=captured.append)

    # No Iceberg namespace on the scope → lake stage skipped (static single-tenant asset).
    assert [c["source"]["type"] for c in captured] == ["clickhouse", "dbt"]
    assert result.stages == [STAGE_CLICKHOUSE, STAGE_DBT]
    assert result.service_name == "novasight_clickhouse"
    assert result.scoped_database == "tenant_local"


def test_run_catalog_ingestion_includes_iceberg_when_namespace_set(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    captured: list[dict[str, Any]] = []

    result = run_catalog_ingestion(
        _settings(), manifest, _scope(iceberg_namespace="ns_acme"), ingest=captured.append
    )

    # Lake hop sits between ClickHouse metadata and dbt (source → Iceberg → ClickHouse).
    assert [c["source"]["type"] for c in captured] == ["clickhouse", "iceberg", "dbt"]
    assert result.stages == [STAGE_CLICKHOUSE, STAGE_ICEBERG, STAGE_DBT]


def test_run_catalog_ingestion_iceberg_stage_is_best_effort(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    seen: list[str] = []

    def ingest(cfg: dict[str, Any]) -> None:
        kind = cfg["source"]["type"]
        if kind == "iceberg":
            raise RuntimeError("OM iceberg connector blew up")  # immature connector
        seen.append(kind)

    # A failing Iceberg scan must NOT abort the run: ClickHouse + dbt still ingest, and
    # the lake hop is left to the lineage stage. STAGE_ICEBERG is omitted from the result.
    result = run_catalog_ingestion(
        _settings(), manifest, _scope(iceberg_namespace="ns_acme"), ingest=ingest
    )
    assert seen == ["clickhouse", "dbt"]
    assert result.stages == [STAGE_CLICKHOUSE, STAGE_DBT]


def test_run_catalog_ingestion_is_tenant_scoped(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    captured: list[dict[str, Any]] = []

    run_catalog_ingestion(_settings(), manifest, _scope("acme"), ingest=captured.append)

    metadata_cfg = captured[0]
    assert metadata_cfg["source"]["sourceConfig"]["config"]["schemaFilterPattern"][
        "includes"
    ] == ["acme"]
    # The whole rendered metadata stage is scoped to this tenant only.
    assert "tenant_local" not in json.dumps(metadata_cfg)
