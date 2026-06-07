"""Codegen — render registry definitions into the artifacts engines consume.

Currently: semantic-model definitions → Cube model files (``cube_model``). The
render functions are pure (definition in, source string out) so they are unit-tested
without any running engine; a thin writer persists the output to the shared model
volume. As dynamic dbt/orchestration land (#4-#7), more renderers join here.
"""
from __future__ import annotations

from app.codegen.cube_model import (
    CubeModelInput,
    render_tenant_models,
    tenant_model_relpath,
    write_tenant_models,
)
from app.codegen.dbt_model import (
    DbtModelInput,
    DbtTestInput,
    render_model_sql,
    render_schema_yml,
)
from app.codegen.dbt_model import (
    tenant_dir_relpath as dbt_tenant_dir_relpath,
)
from app.codegen.dbt_model import (
    write_tenant_models as write_tenant_dbt_models,
)

__all__ = [
    "CubeModelInput",
    "DbtModelInput",
    "DbtTestInput",
    "dbt_tenant_dir_relpath",
    "render_model_sql",
    "render_schema_yml",
    "render_tenant_models",
    "tenant_model_relpath",
    "write_tenant_dbt_models",
    "write_tenant_models",
]
