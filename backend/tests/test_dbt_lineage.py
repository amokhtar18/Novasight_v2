"""Unit tests for dbt lineage parsing + graph building (#5) — pure, no DB."""
from __future__ import annotations

from app.models.dbt_model import DbtModel
from app.services.dbt_lineage import build_lineage, parse_dependencies


def _m(name: str, sql: str | None, layer: str = "marts") -> DbtModel:
    return DbtModel(name=name, sql=sql, layer=layer, materialization="table")


def test_parse_dependencies_refs_and_sources() -> None:
    refs, sources = parse_dependencies(
        "select * from {{ ref('stg_orders') }} a "
        "join {{ source('raw', 'customers') }} b on a.id = b.id"
    )
    assert refs == ["stg_orders"]
    assert sources == ["raw.customers"]


def test_parse_dependencies_dedupes_and_handles_none() -> None:
    refs, _ = parse_dependencies("{{ ref('a') }} ... {{ ref('a') }}")
    assert refs == ["a"]
    assert parse_dependencies(None) == ([], [])


def test_build_lineage_model_and_source_edges() -> None:
    g = build_lineage(
        [
            _m("stg_orders", "select * from {{ source('raw', 'orders') }}", "staging"),
            _m("mart_sales", "select * from {{ ref('stg_orders') }}", "marts"),
        ]
    )
    ids = {n.id for n in g.nodes}
    assert {"model:stg_orders", "model:mart_sales", "source:raw.orders"} <= ids
    pairs = {(e.source, e.target) for e in g.edges}
    assert ("source:raw.orders", "model:stg_orders") in pairs
    assert ("model:stg_orders", "model:mart_sales") in pairs


def test_build_lineage_unknown_ref_is_external() -> None:
    g = build_lineage([_m("mart_x", "select * from {{ ref('not_registered') }}")])
    by_id = {n.id: n for n in g.nodes}
    assert by_id["external:not_registered"].kind == "external"
    pairs = {(e.source, e.target) for e in g.edges}
    assert ("external:not_registered", "model:mart_x") in pairs
