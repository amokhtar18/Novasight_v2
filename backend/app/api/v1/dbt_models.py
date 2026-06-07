"""dbt model + test registry endpoints — the dbt wizard (#5/#6).

CRUD over a tenant's dbt model definitions (with their data tests). On every change
the service regenerates the tenant's dbt project subtree (codegen is the single
writer); the dynamic dbt run (#7) materializes it to ClickHouse.

Reads need only a tenant context. Mutations require the tenant **superuser** role —
defining transformations writes to the shared dbt project and runs against the data
plane. The tenant is resolved from the JWT, never a body/path value.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response, status

from app.core.security import Principal, require_tenant_superuser
from app.models.dbt_model import DbtModel
from app.schemas.dbt_model import (
    DbtModelCreate,
    DbtModelRead,
    DbtModelUpdate,
    DbtTestRead,
)
from app.services.dbt_models import DbtModelService, get_dbt_model_service
from app.tenancy.context import TenantContext, get_tenant_context

router = APIRouter(prefix="/dbt-models", tags=["dbt-models"])


def _to_read(m: DbtModel) -> DbtModelRead:
    return DbtModelRead(
        id=m.id,
        name=m.name,
        layer=m.layer,
        materialization=m.materialization,
        sql=m.sql,
        config=m.config,
        enabled=m.enabled,
        tests=[
            DbtTestRead(
                id=t.id, column_name=t.column_name, test_type=t.test_type, config=t.config
            )
            for t in m.tests
        ],
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


@router.get("", response_model=list[DbtModelRead])
async def list_dbt_models(
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    svc: DbtModelService = Depends(get_dbt_model_service),  # noqa: B008
) -> list[DbtModelRead]:
    """List the tenant's dbt model definitions."""
    return [_to_read(m) for m in await svc.list_for_tenant(ctx)]


@router.get("/{model_id}", response_model=DbtModelRead)
async def get_dbt_model(
    model_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    svc: DbtModelService = Depends(get_dbt_model_service),  # noqa: B008
) -> DbtModelRead:
    """Fetch one dbt model (404 if not in the caller's tenant)."""
    return _to_read(await svc.get_for_tenant(ctx, model_id))


@router.post("", response_model=DbtModelRead, status_code=status.HTTP_201_CREATED)
async def create_dbt_model(
    payload: DbtModelCreate,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    _: Principal = Depends(require_tenant_superuser),  # noqa: B008
    svc: DbtModelService = Depends(get_dbt_model_service),  # noqa: B008
) -> DbtModelRead:
    """Define a dbt model + tests (regenerates the tenant's dbt codegen)."""
    return _to_read(await svc.create(ctx, payload))


@router.patch("/{model_id}", response_model=DbtModelRead)
async def update_dbt_model(
    model_id: uuid.UUID,
    payload: DbtModelUpdate,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    _: Principal = Depends(require_tenant_superuser),  # noqa: B008
    svc: DbtModelService = Depends(get_dbt_model_service),  # noqa: B008
) -> DbtModelRead:
    """Update a dbt model (partial; ``tests`` replaces all; regenerates codegen)."""
    return _to_read(await svc.update(ctx, model_id, payload))


@router.delete("/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dbt_model(
    model_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    _: Principal = Depends(require_tenant_superuser),  # noqa: B008
    svc: DbtModelService = Depends(get_dbt_model_service),  # noqa: B008
) -> Response:
    """Delete a dbt model (regenerates the tenant's dbt codegen)."""
    await svc.delete(ctx, model_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
