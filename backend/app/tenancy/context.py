"""Tenant context and the ``get_tenant_context`` FastAPI dependency.

``TenantContext`` is the frozen, immutable token passed through every
data-touching code path. It carries only what other layers need: the tenant's
internal id and the three physical resource coordinates.

All field values are sourced from the persisted ``TenantResourceMap`` row —
never recomputed, never accepted from a client request. This is the
authoritative source-of-truth invariant required by the ``tenancy-isolation``
skill.

Fail-closed rules:
- Tenant not found in registry → 403.
- Tenant exists but is ``suspended`` → 403.
- Tenant found but has no ``resource_map`` → 403 (data integrity guard).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import Depends, HTTPException

from app.core.security import Principal, get_principal
from app.tenancy.registry import TenantRegistry, get_tenant_registry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TenantContext:
    """Immutable per-request tenant scope.

    All fields are derived from the control-plane DB, never from the client.
    """

    tenant_id: str          # str(UUID) of the Tenant row
    iceberg_namespace: str  # from TenantResourceMap.iceberg_namespace
    clickhouse_db: str      # from TenantResourceMap.clickhouse_db
    dbt_schema: str         # from TenantResourceMap.dbt_schema


async def get_tenant_context(
    principal: Principal = Depends(get_principal),       # noqa: B008
    registry: TenantRegistry = Depends(get_tenant_registry),  # noqa: B008
) -> TenantContext:
    """FastAPI dependency: resolve the tenant from the principal's tenant claim.

    Composes ``get_principal`` + ``get_tenant_registry``.  Fails closed (403)
    if the tenant is missing, suspended, or has no resource map.  The
    ``principal.tenant_key`` comes from the verified JWT — never from the
    request body.
    """
    tenant = await registry.resolve(principal.tenant_key)

    if tenant is None:
        logger.warning("Tenant not found for slug=%r", principal.tenant_key)
        raise HTTPException(status_code=403, detail="Tenant context unavailable")

    if tenant.status != "active":
        logger.warning(
            "Tenant slug=%r is not active (status=%r)", principal.tenant_key, tenant.status
        )
        raise HTTPException(status_code=403, detail="Tenant context unavailable")

    resource_map = tenant.resource_map
    if resource_map is None:
        logger.error(
            "Tenant slug=%r is active but has no resource_map", principal.tenant_key
        )
        raise HTTPException(status_code=403, detail="Tenant context unavailable")

    return TenantContext(
        tenant_id=str(tenant.id),
        iceberg_namespace=resource_map.iceberg_namespace,
        clickhouse_db=resource_map.clickhouse_db,
        dbt_schema=resource_map.dbt_schema,
    )
