"""Tests for the dbt codegen (#5/#6) — pure render, no dbt needed.

Verifies the model ``.sql`` carries a materialization config header + the user SQL,
the ``schema.yml`` groups column vs model tests and encodes parametrized tests, and
the writer prunes stale model files on rename/delete.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from app.codegen import (
    DbtModelInput,
    DbtTestInput,
    render_model_sql,
    render_schema_yml,
    write_tenant_dbt_models,
)


def _model() -> DbtModelInput:
    return DbtModelInput(
        name="mart_orders",
        materialization="table",
        sql="select region, sum(amount) as total from {{ ref('stg_orders') }} group by 1",
        tests=[
            DbtTestInput(test_type="not_null", column_name="region"),
            DbtTestInput(test_type="unique", column_name="region"),
            DbtTestInput(
                test_type="accepted_values",
                column_name="region",
                config={"values": ["west", "east"]},
            ),
        ],
    )


def test_render_model_sql_has_config_header() -> None:
    sql = render_model_sql(_model())
    assert sql.startswith("{{ config(materialized='table') }}")
    assert "sum(amount) as total" in sql


def test_render_incremental_config_header() -> None:
    model = DbtModelInput(
        name="mart_orders",
        materialization="incremental",
        sql="select * from {{ ref('stg_orders') }}",
        unique_key=["order_id", "line_no"],
        incremental_strategy="merge",
        on_schema_change="append_new_columns",
    )
    header = render_model_sql(model).splitlines()[0]
    assert header == (
        "{{ config(materialized='incremental', unique_key=['order_id', 'line_no'], "
        "incremental_strategy='merge', on_schema_change='append_new_columns') }}"
    )


def test_incremental_args_only_for_incremental_materialization() -> None:
    # unique_key on a non-incremental model is ignored (no upsert config leaks in).
    model = DbtModelInput(
        name="m", materialization="table", sql="select 1", unique_key=["id"]
    )
    assert render_model_sql(model).startswith("{{ config(materialized='table') }}")


def test_render_schema_yml_groups_tests() -> None:
    parsed = yaml.safe_load(render_schema_yml([_model()]))
    assert parsed["version"] == 2
    model = parsed["models"][0]
    assert model["name"] == "mart_orders"
    region = next(c for c in model["columns"] if c["name"] == "region")
    assert "not_null" in region["data_tests"]
    assert "unique" in region["data_tests"]
    # Parametrized test rendered as a config dict.
    accepted = next(t for t in region["data_tests"] if isinstance(t, dict))
    assert accepted["accepted_values"]["values"] == ["west", "east"]


def test_render_relationships_test() -> None:
    model = DbtModelInput(
        name="mart_orders",
        materialization="table",
        sql="select customer_id from {{ ref('stg_orders') }}",
        tests=[
            DbtTestInput(
                test_type="relationships",
                column_name="customer_id",
                config={"to": "ref('stg_customers')", "field": "id"},
            )
        ],
    )
    parsed = yaml.safe_load(render_schema_yml([model]))
    col = next(c for c in parsed["models"][0]["columns"] if c["name"] == "customer_id")
    rel = next(t for t in col["data_tests"] if isinstance(t, dict))
    assert rel["relationships"] == {"to": "ref('stg_customers')", "field": "id"}


def test_writer_prunes_stale_models(tmp_path: Path) -> None:
    root = str(tmp_path / "models")
    write_tenant_dbt_models(root, "tenant_acme", [_model()])
    tdir = tmp_path / "models" / "tenant_acme"
    assert (tdir / "mart_orders.sql").exists()
    assert (tdir / "schema.yml").exists()

    # Rename the model → the old .sql is pruned, the new one written.
    renamed = DbtModelInput(name="mart_orders_v2", materialization="view", sql="select 1")
    write_tenant_dbt_models(root, "tenant_acme", [renamed])
    assert not (tdir / "mart_orders.sql").exists()
    assert (tdir / "mart_orders_v2.sql").exists()
