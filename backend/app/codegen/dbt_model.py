"""Render dbt model definitions into a per-tenant dbt project subtree (#5/#6).

Each tenant's wizard models are written under ``<models_dir>/tenant_<dbt_schema>/`` as
one ``<name>.sql`` per model (with a ``{{ config(materialized=...) }}`` header) plus a
single ``schema.yml`` describing columns + data tests. The dynamic dbt run (#7) builds
that subtree against the tenant's target schema; isolation is by directory + target
schema, mirroring the semantic codegen.

The render functions are pure (definitions in, source strings out) so they are unit-
tested without dbt; a thin writer persists them and prunes stale ``.sql`` files on
rename/delete. The model ``sql`` is the user's transformation, written verbatim.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# dbt schema.yml is version 2; tests live under ``data_tests`` (dbt >= 1.8).
_SCHEMA_FILENAME = "schema.yml"


@dataclass(frozen=True)
class DbtTestInput:
    """One data test (column-level when ``column_name`` is set)."""

    test_type: str
    column_name: str | None = None
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DbtModelInput:
    """One model to render.

    The ``unique_key`` / ``incremental_strategy`` / ``on_schema_change`` fields are
    only emitted for ``materialization == "incremental"``; they originate from the
    validated ``IncrementalConfig`` (identifiers + closed literals), so they are safe
    to interpolate into the dbt ``config()`` header.
    """

    name: str
    materialization: str
    sql: str
    tests: list[DbtTestInput] = field(default_factory=list)
    unique_key: list[str] = field(default_factory=list)
    incremental_strategy: str | None = None
    on_schema_change: str | None = None


def tenant_dir_relpath(dbt_schema: str) -> str:
    """A tenant's generated-models subdir, relative to the dbt models root.

    The dbt schema (e.g. ``tenant_local``) is already a per-tenant, collision-safe name
    (see ``tenancy.resources``), so it is used directly as the subdir — prefixing it
    again would double it to ``tenant_tenant_local``.
    """
    return dbt_schema


def render_model_sql(model: DbtModelInput) -> str:
    """Render one model's ``.sql`` — a materialization config header + the user SQL.

    For incremental models the header also carries ``unique_key`` (so runs upsert),
    ``incremental_strategy``, and ``on_schema_change`` when provided.
    """
    args = [f"materialized='{model.materialization}'"]
    if model.materialization == "incremental":
        if model.unique_key:
            keys = ", ".join(f"'{k}'" for k in model.unique_key)
            args.append(f"unique_key=[{keys}]")
        if model.incremental_strategy:
            args.append(f"incremental_strategy='{model.incremental_strategy}'")
        if model.on_schema_change:
            args.append(f"on_schema_change='{model.on_schema_change}'")
    header = f"{{{{ config({', '.join(args)}) }}}}"
    return f"{header}\n\n{model.sql.strip()}\n"


def render_schema_yml(models: list[DbtModelInput]) -> str:
    """Render the tenant ``schema.yml`` (model + column data tests)."""
    out_models: list[dict[str, Any]] = []
    for model in models:
        model_tests: list[Any] = []
        columns: dict[str, list[Any]] = {}
        for test in model.tests:
            entry = _test_entry(test)
            if test.column_name:
                columns.setdefault(test.column_name, []).append(entry)
            else:
                model_tests.append(entry)

        model_dict: dict[str, Any] = {"name": model.name}
        if model_tests:
            model_dict["data_tests"] = model_tests
        if columns:
            model_dict["columns"] = [
                {"name": col, "data_tests": tests} for col, tests in columns.items()
            ]
        out_models.append(model_dict)

    return str(yaml.safe_dump({"version": 2, "models": out_models}, sort_keys=False))


def write_tenant_models(
    models_dir: str, dbt_schema: str, models: list[DbtModelInput]
) -> Path:
    """Write a tenant's ``.sql`` files + ``schema.yml`` into its subdir.

    Idempotent: the subdir is (re)created, current files written, and stale ``.sql``
    files (from a rename/delete) pruned. Returns the tenant subdir path.
    """
    directory = Path(models_dir) / tenant_dir_relpath(dbt_schema)
    directory.mkdir(parents=True, exist_ok=True)

    wanted = {f"{m.name}.sql" for m in models}
    for model in models:
        (directory / f"{model.name}.sql").write_text(render_model_sql(model), encoding="utf-8")
    (directory / _SCHEMA_FILENAME).write_text(render_schema_yml(models), encoding="utf-8")

    # Prune stale model files (keep the schema.yml).
    for existing in directory.glob("*.sql"):
        if existing.name not in wanted:
            existing.unlink()

    return directory


def _test_entry(test: DbtTestInput) -> str | dict[str, Any]:
    """Map a test to its dbt ``data_tests`` entry (bare string or a config dict)."""
    if test.test_type in ("not_null", "unique"):
        return test.test_type
    if test.test_type == "accepted_values":
        return {"accepted_values": {"values": list(test.config.get("values", []))}}
    if test.test_type == "relationships":
        return {
            "relationships": {
                "to": test.config.get("to", ""),
                "field": test.config.get("field", ""),
            }
        }
    return test.test_type
