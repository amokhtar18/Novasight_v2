"""Control-plane tenant provisioning endpoints (Task 6.3).

These routes are NOT tenant-scoped — they create and destroy tenants — so they do
*not* depend on ``get_tenant_context``. They are gated by ``require_platform_admin``
(a platform role, configured via ``settings.auth.platform_admin_role``). The tenant's
physical resources are derived from the slug by the provisioner, never accepted from
the caller (tenancy-isolation invariant).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.core.security import require_platform_admin
from app.models import Tenant
from app.schemas.tenant import TenantProvisionRequest, TenantRead
from app.tenancy.provisioning import (
    ResourceConflictError,
    TenantAlreadyExistsError,
    TenantNotFoundError,
    TenantProvisioner,
    get_tenant_provisioner,
)

router = APIRouter(
    prefix="/tenants",
    tags=["tenants"],
    dependencies=[Depends(require_platform_admin)],
)


def _to_read(tenant: Tenant) -> TenantRead:
    rmap = tenant.resource_map
    return TenantRead(
        id=str(tenant.id),
        slug=tenant.slug,
        name=tenant.name,
        status=tenant.status,
        iceberg_namespace=rmap.iceberg_namespace,
        clickhouse_db=rmap.clickhouse_db,
        dbt_schema=rmap.dbt_schema,
    )


@router.post("", response_model=TenantRead, status_code=status.HTTP_201_CREATED)
async def provision_tenant(
    payload: TenantProvisionRequest,
    provisioner: TenantProvisioner = Depends(get_tenant_provisioner),  # noqa: B008
) -> TenantRead:
    """Provision a new, fully isolated tenant environment (atomic)."""
    try:
        tenant = await provisioner.provision(
            slug=payload.slug, name=payload.name, admin_email=payload.admin_email
        )
    except ValueError as exc:  # invalid slug
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TenantAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail="Tenant already exists") from exc
    except ResourceConflictError as exc:
        raise HTTPException(
            status_code=409, detail="A conflicting resource already exists"
        ) from exc
    return _to_read(tenant)


@router.delete("/{slug}", status_code=status.HTTP_204_NO_CONTENT)
async def deprovision_tenant(
    slug: str,
    provisioner: TenantProvisioner = Depends(get_tenant_provisioner),  # noqa: B008
) -> Response:
    """De-provision a tenant: drop its physical resources and registry entry."""
    try:
        await provisioner.deprovision(slug=slug)
    except TenantNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Tenant not found") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
