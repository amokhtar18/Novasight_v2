"""Serving-layer introspection endpoints — tables + columns for the wizard (#6).

Read-only and tenant-scoped (the database is resolved from the JWT, never a path/query
value). Used by the semantic-model wizard to offer real base-table and column dropdowns.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, status

from app.schemas.serving import ServingColumn
from app.services.serving import ServingService, get_serving_service
from app.tenancy.context import TenantContext, get_tenant_context

router = APIRouter(prefix="/serving", tags=["serving"])

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@router.get("/tables", response_model=list[str])
async def list_serving_tables(
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    svc: ServingService = Depends(get_serving_service),  # noqa: B008
) -> list[str]:
    """List the tenant's serving (ClickHouse) table names."""
    return svc.list_tables(ctx)


@router.get("/tables/{table}/columns", response_model=list[ServingColumn])
async def list_serving_columns(
    table: str,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    svc: ServingService = Depends(get_serving_service),  # noqa: B008
) -> list[ServingColumn]:
    """List the columns (name + type) of one serving table."""
    if not _IDENTIFIER.match(table):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid table name"
        )
    return svc.list_columns(ctx, table)
