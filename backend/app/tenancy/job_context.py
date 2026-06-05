"""Resolve a ``TenantContext`` inside a background job (no HTTP request).

Golden rule 2 (tenancy is a cross-cutting invariant) must hold for background
work exactly as it does for request handlers. A job is handed only a *tenant
slug* (an opaque, already-trusted handle persisted on the work item) — never a
resource map. This module re-derives the full tenant scope from the
authoritative control-plane row via the same ``TenantRegistry`` the HTTP boundary
uses, applying the *same* fail-closed checks:

- tenant not found            → ``JobTenantError``
- tenant not ``active``       → ``JobTenantError``
- tenant has no resource map  → ``JobTenantError``

The difference from ``get_tenant_context`` is only the failure surface: a worker
raises a domain error (which Dramatiq turns into a retry/dead-letter) instead of
an HTTP 403. The *source of truth* and the checks are identical, so a job can
never operate on a tenant scope that a request couldn't.
"""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.tenancy.context import TenantContext
from app.tenancy.registry import TenantRegistry

logger = logging.getLogger(__name__)


class JobTenantError(RuntimeError):
    """A background job's tenant could not be resolved to a usable scope."""


async def resolve_tenant_context_for_job(slug: str, db: AsyncSession) -> TenantContext:
    """Resolve ``slug`` to a fully-scoped ``TenantContext`` for a worker job.

    Fails closed (raises ``JobTenantError``) if the tenant is missing, suspended,
    or has no resource map — never returns a partial or guessed scope.
    """
    tenant = await TenantRegistry(db).resolve(slug)

    if tenant is None:
        logger.warning("Job tenant not found for slug=%r", slug)
        raise JobTenantError(f"tenant {slug!r} not found")

    if tenant.status != "active":
        logger.warning("Job tenant slug=%r is not active (status=%r)", slug, tenant.status)
        raise JobTenantError(f"tenant {slug!r} is not active")

    resource_map = tenant.resource_map
    if resource_map is None:
        logger.error("Job tenant slug=%r is active but has no resource_map", slug)
        raise JobTenantError(f"tenant {slug!r} has no resource map")

    return TenantContext(
        tenant_id=str(tenant.id),
        iceberg_namespace=resource_map.iceberg_namespace,
        clickhouse_db=resource_map.clickhouse_db,
        dbt_schema=resource_map.dbt_schema,
    )
