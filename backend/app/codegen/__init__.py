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

__all__ = [
    "CubeModelInput",
    "render_tenant_models",
    "tenant_model_relpath",
    "write_tenant_models",
]
