"""Tests for the cross-system lineage stage (``catalog_lineage.py``).

The edge builders are pure and the emission is injected, so the whole unit runs
without a live OpenMetadata server (mirroring ``test_catalog``). We assert:

* the right ``source → Iceberg → ClickHouse`` and ``ClickHouse → Cube`` edges are
  produced from registry rows (with and without an Iceberg namespace);
* every endpoint is scoped to the tenant's own namespace / database (golden rule 2);
* ``run_lineage`` emits exactly those edges, and emits nothing when there are none.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import novasight_orchestration.catalog_lineage as cl
from novasight_orchestration.catalog import CatalogScope
from novasight_orchestration.catalog_lineage import (
    STAGE_LINEAGE,
    LineageEdge,
    _emit_lineage,
    build_pipeline_edges,
    build_semantic_edges,
    clickhouse_ref,
    cube_ref,
    iceberg_ref,
    run_lineage,
    source_ref,
)
from novasight_orchestration.registry import CatalogPipelineRow, CatalogSemanticRow


def _secret(value: str) -> Any:
    return SimpleNamespace(get_secret_value=lambda: value)


def _settings() -> Any:
    """Stand-in exposing only ``settings.catalog`` (all the ref builders read)."""
    return SimpleNamespace(
        catalog=SimpleNamespace(
            service_name="novasight_clickhouse",
            iceberg_service_name="novasight_iceberg",
            source_service_name="novasight_sources",
            semantic_service_name="novasight_semantic",
            host_port="http://openmetadata:8585/api",
            jwt_token=_secret("jwt-tok"),
            runner_python="/opt/om-venv/bin/python",
        )
    )


def _scope(*, iceberg_namespace: str | None = None) -> CatalogScope:
    return CatalogScope(
        clickhouse_db="tenant_acme", iceberg_namespace=iceberg_namespace, tenant="acme"
    )


def _pipeline(**kw: Any) -> CatalogPipelineRow:
    base = dict(
        name="orders_pipe",
        target_table="orders",
        source_kind="sql_database",
        source_name="prod_pg",
        source_object="orders",
        source_schema="public",
    )
    base.update(kw)
    return CatalogPipelineRow(**base)  # type: ignore[arg-type]


# --- ref builders: coordinates + FQN, tenant-scoped -------------------------------


def test_refs_are_tenant_scoped_and_fqn_is_four_parts() -> None:
    scope = _scope(iceberg_namespace="ns_acme")
    ch = clickhouse_ref(_settings(), scope, "orders")
    ice = iceberg_ref(_settings(), scope, "orders")
    cube = cube_ref(_settings(), scope, "Orders")

    assert ch.fqn == "novasight_clickhouse.default.tenant_acme.orders"
    assert ice.fqn == "novasight_iceberg.default.ns_acme.orders"
    assert cube.fqn == "novasight_semantic.default.tenant_acme.Orders"


def test_source_ref_uses_schema_then_falls_back_to_connection_name() -> None:
    with_schema = source_ref(_settings(), _pipeline(source_schema="public"))
    assert with_schema.fqn == "novasight_sources.default.public.orders"

    # Files have no schema → the connection name stands in.
    a_file = source_ref(
        _settings(),
        _pipeline(source_kind="filesystem", source_schema="", source_name="dropbox_csv"),
    )
    assert a_file.schema == "dropbox_csv"


# --- pipeline edges: source -> Iceberg -> ClickHouse ------------------------------


def test_pipeline_edges_include_lake_hop_when_namespace_set() -> None:
    edges = build_pipeline_edges(_settings(), _scope(iceberg_namespace="ns_acme"), [_pipeline()])

    assert [(e.from_ref.fqn, e.to_ref.fqn) for e in edges] == [
        ("novasight_sources.default.public.orders", "novasight_iceberg.default.ns_acme.orders"),
        ("novasight_iceberg.default.ns_acme.orders", "novasight_clickhouse.default.tenant_acme.orders"),
    ]


def test_pipeline_edges_link_source_to_clickhouse_without_namespace() -> None:
    edges = build_pipeline_edges(_settings(), _scope(), [_pipeline()])

    assert [(e.from_ref.fqn, e.to_ref.fqn) for e in edges] == [
        ("novasight_sources.default.public.orders", "novasight_clickhouse.default.tenant_acme.orders"),
    ]


# --- semantic edges: ClickHouse base table -> Cube cube ---------------------------


def test_semantic_edges_link_base_table_to_cube() -> None:
    models = [CatalogSemanticRow(name="Orders", base_table="serving_orders")]
    edges = build_semantic_edges(_settings(), _scope(), models)

    assert len(edges) == 1
    assert edges[0].from_ref.fqn == "novasight_clickhouse.default.tenant_acme.serving_orders"
    assert edges[0].to_ref.fqn == "novasight_semantic.default.tenant_acme.Orders"


# --- run_lineage: emits exactly the built edges, scoped, never widened ------------


def test_run_lineage_emits_all_edges_and_counts_them() -> None:
    captured: list[list[LineageEdge]] = []
    result = run_lineage(
        _settings(),
        _scope(iceberg_namespace="ns_acme"),
        [_pipeline()],
        [CatalogSemanticRow(name="Orders", base_table="serving_orders")],
        emit=lambda edges, settings: captured.append(edges),
    )

    assert result.stage == STAGE_LINEAGE
    assert result.edge_count == 3  # 2 pipeline edges + 1 semantic edge
    assert len(captured) == 1 and len(captured[0]) == 3
    # No cross-tenant bleed: every endpoint is in this tenant's surfaces.
    rendered = json.dumps([[e.from_ref.fqn, e.to_ref.fqn] for e in captured[0]])
    assert "tenant_acme" in rendered and "ns_acme" in rendered
    assert "tenant_other" not in rendered


def test_run_lineage_does_not_emit_when_there_are_no_edges() -> None:
    calls: list[object] = []
    result = run_lineage(
        _settings(), _scope(), [], [], emit=lambda edges, settings: calls.append(edges)
    )
    assert result.edge_count == 0
    assert calls == []  # nothing to emit → emitter not called


# --- _emit_lineage: serialises edges + server creds to the isolated runner --------


def test_emit_lineage_hands_payload_to_isolated_runner(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        cl,
        "run_om_runner",
        lambda mode, payload, *, python: captured.update(mode=mode, payload=payload, python=python),
    )
    edges = build_pipeline_edges(_settings(), _scope(iceberg_namespace="ns_acme"), [_pipeline()])

    _emit_lineage(edges, _settings())

    assert captured["mode"] == "lineage"
    assert captured["python"] == "/opt/om-venv/bin/python"
    # Server creds travel with the payload (the runner has no settings of its own).
    assert captured["payload"]["server"] == {
        "host_port": "http://openmetadata:8585/api",
        "jwt_token": "jwt-tok",
    }
    # Edges are plain coordinate dicts, in order.
    first = captured["payload"]["edges"][0]
    assert first["from"] == {
        "service": "novasight_sources", "database": "default", "schema": "public", "table": "orders"
    }
    assert first["to"]["service"] == "novasight_iceberg"
