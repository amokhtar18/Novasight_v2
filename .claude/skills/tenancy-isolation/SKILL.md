---
name: tenancy-isolation
description: >
  The multi-tenancy invariant for Analytica. Apply whenever code reads or writes data,
  resolves storage locations, builds queries, runs pipelines, or handles auth. Enforces
  pooled compute with per-tenant isolated data (Iceberg namespace, ClickHouse database,
  dbt schema), with tenant context resolved at the boundary and never trusted from the
  client.
---

# Tenancy isolation

**Model: shared application & orchestration tier, isolated data per tenant.**
- Storage: each tenant has its own Iceberg **namespace / object-store prefix**.
- Serving: each tenant has its own **ClickHouse database**.
- Transform: each tenant maps to its own **dbt target schema**.
- Registry: a control-plane Postgres holds tenants, users, connectors, and the mapping
  to the above resources.

On-prem single-tenant installs run the **same code path** with exactly one tenant.

## The invariant

1. **Resolve at the boundary.** Tenant context is derived once, from the authenticated
   principal (JWT/OIDC claim → tenant registry lookup), in middleware/dependency.
   Provide it everywhere via `Depends(get_tenant_context)`.
2. **Never trust the client for identity.** A tenant id in a request body, query
   string, or header chosen by the client is ignored. The only authority is the
   authenticated context.
3. **Derive resources, don't pass them.** Namespace, database, and schema are computed
   from the tenant context, not accepted as parameters from callers.
4. **No cross-tenant reach.** Every query, pipeline run, cache key, file path, and log
   scope includes the tenant. Cache keys and queues are namespaced by tenant id.
5. **Fail closed.** If tenant context is missing or unresolved, reject the request —
   never default to a shared or "admin" scope.

## Reference pattern
```python
# app/tenancy/context.py
from dataclasses import dataclass
from fastapi import Depends, HTTPException

@dataclass(frozen=True)
class TenantContext:
    tenant_id: str
    iceberg_namespace: str
    clickhouse_db: str
    dbt_schema: str

async def get_tenant_context(principal = Depends(get_principal),
                             registry = Depends(get_tenant_registry)) -> TenantContext:
    tenant = await registry.resolve(principal.tenant_id)  # from authenticated claim
    if tenant is None:
        raise HTTPException(403, "no tenant context")      # fail closed
    return TenantContext(
        tenant_id=tenant.id,
        iceberg_namespace=f"{tenant.slug}",                # derived, not client-supplied
        clickhouse_db=f"tenant_{tenant.slug}",
        dbt_schema=f"tenant_{tenant.slug}",
    )
```

## Testing requirement
Every data-touching feature ships with a test proving tenant A cannot read or write
tenant B's data through the new path. This is enforced by the reviewer.
