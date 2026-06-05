"""Tenant context and resource resolution.

This package owns the multi-tenancy invariant (see the ``tenancy-isolation``
skill): resources are *derived* from the tenant, never accepted from a caller.
"""
from __future__ import annotations

from app.tenancy.context import TenantContext, get_tenant_context
from app.tenancy.registry import TenantRegistry, get_tenant_registry
from app.tenancy.resources import TenantResources, resources_for_slug

__all__ = [
    "TenantContext",
    "TenantRegistry",
    "TenantResources",
    "get_tenant_context",
    "get_tenant_registry",
    "resources_for_slug",
]
