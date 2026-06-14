"""Tests for the Cube semantic-model codegen (#8) — pure render, no engine needed.

With repositoryFactory, isolation is by directory (one subdir per tenant), so the
generated cubes carry no in-file guard. Verifies cubes + measures/dimensions render,
string values are JSON-encoded, ``count`` omits ``sql``, and the per-tenant relpath.
"""
from __future__ import annotations

from app.codegen import CubeModelInput, render_tenant_models, tenant_model_relpath
from app.schemas.semantic_model import (
    DimensionDef,
    JoinDef,
    MeasureDef,
    SemanticModelConfig,
)


def _config() -> SemanticModelConfig:
    return SemanticModelConfig(
        measures=[
            MeasureDef(name="total_amount", type="sum", sql="amount", title="Total Amount"),
            MeasureDef(name="rows", type="count"),
        ],
        dimensions=[
            DimensionDef(name="region", type="string", sql="region", primary_key=True),
        ],
    )


def test_render_emits_cube_without_guard() -> None:
    js = render_tenant_models([CubeModelInput("sales", "mart_sales", _config())])
    assert "cube(`sales`" in js
    # Directory-isolated → no in-file clickhouse_db equality guard.
    assert "if (COMPILE_CONTEXT" not in js
    # sql_table still resolves the tenant db per request, plus the base table.
    assert "COMPILE_CONTEXT.securityContext.clickhouse_db" in js
    assert "mart_sales" in js
    # Members render with JSON-encoded values.
    assert 'type: "sum"' in js
    assert 'sql: "amount"' in js
    assert 'region: { sql: "region", type: "string"' in js
    assert "public: true" in js
    assert "primaryKey: true" in js


def test_render_joins_block() -> None:
    config = SemanticModelConfig(
        measures=[MeasureDef(name="rows", type="count")],
        joins=[
            JoinDef(
                name="customers",
                relationship="many_to_one",
                local_key="customer_id",
                foreign_key="id",
            )
        ],
    )
    js = render_tenant_models([CubeModelInput("orders", "mart_orders", config)])
    assert "joins: {" in js
    assert "relationship: `many_to_one`" in js
    # The join condition is built from validated identifiers only.
    expected = (
        "customers: { relationship: `many_to_one`, "
        "sql: `${CUBE}.customer_id = ${customers}.id` }"
    )
    assert expected in js


def test_no_joins_block_when_empty() -> None:
    js = render_tenant_models(
        [CubeModelInput("m", "t", SemanticModelConfig(
            measures=[MeasureDef(name="rows", type="count")],
        ))]
    )
    assert "joins:" not in js


def test_count_measure_omits_sql() -> None:
    js = render_tenant_models(
        [CubeModelInput("m", "t", SemanticModelConfig(
            measures=[MeasureDef(name="rows", type="count")],
        ))]
    )
    assert 'rows: { type: "count" }' in js


def test_empty_models_emit_no_cubes() -> None:
    js = render_tenant_models([])
    assert "cube(" not in js


def test_tenant_relpath_is_per_db_subdir() -> None:
    assert tenant_model_relpath("abc") == "abc/models.js"
