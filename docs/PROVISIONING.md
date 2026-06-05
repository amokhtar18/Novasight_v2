# Tenant provisioning (Phase 6.3)

Provisioning creates a new tenant's **fully isolated, queryable environment** as one
all-or-nothing unit; de-provisioning tears it down. It is the control-plane operation
behind multi-tenant onboarding — and on-prem single-tenant installs run the exact same
path once at bootstrap.

## What a tenant gets

Per the [tenancy-isolation](../.claude/skills/tenancy-isolation/SKILL.md) invariant, a
tenant's data lives in three isolated homes plus a registry entry:

| Resource | System | Name (derived from slug) |
|----------|--------|--------------------------|
| Iceberg namespace | REST catalog / object store | `<slug>` |
| ClickHouse database | serving tier | `tenant_<slug>` |
| dbt target schema | transform tier | `tenant_<slug>` |
| Registry entry | control-plane Postgres | `Tenant` + `TenantResourceMap` + admin `User` |

In this ClickHouse-backed deployment the **dbt schema is a ClickHouse database**, and
[`resources.py`](../backend/app/tenancy/resources.py) gives it the same name as the
serving database — so they are one physical database (a second `CREATE DATABASE` only
runs if an operator configures them to differ). All names are **derived from the
validated slug**, never accepted from the caller.

## Atomicity without 2PC — the saga

These resources span three systems with no distributed transaction, so
[`provisioning.py`](../backend/app/tenancy/provisioning.py) uses a **saga**:

1. create the Iceberg namespace → push its compensating drop;
2. create the ClickHouse database → push its compensating drop;
3. create the dbt schema (only if distinct) → push its compensating drop;
4. write the registry rows and **commit last**.

If any step fails, the registry transaction is rolled back and every compensation runs
in **reverse order**. Crucially, only resources **this call created** are ever dropped:
if a physical resource already exists for an unregistered tenant, provisioning **fails
closed** (`ResourceConflictError`, HTTP 409) rather than adopting or destroying it.

De-provisioning drops physical resources first (idempotent: purge tables → drop
namespace → drop database), then deletes the registry row (which cascades to the
resource map, users, and datasets).

## API

Both routes are **not tenant-scoped** (they create/destroy tenants) and are gated by
the platform-admin role (`settings.auth.platform_admin_role`, env
`AUTH__PLATFORM_ADMIN_ROLE`, default `platform_admin`). A non-admin caller gets 403; an
unauthenticated caller gets 401.

```
POST /api/v1/tenants            # body: { slug, name, admin_email }  -> 201 TenantRead
DELETE /api/v1/tenants/{slug}                                        -> 204
```

| Status | Meaning |
|--------|---------|
| 201 | provisioned; body returns the derived resource coordinates |
| 422 | slug is not a safe identifier fragment |
| 409 | tenant already registered, or a conflicting physical resource exists |
| 404 | (delete) no such tenant |

## Isolation guarantee

`backend/tests/test_provisioning.py` proves a failed provision of tenant B leaves
tenant A's namespace, database, and registry row fully intact — the cross-tenant
isolation test the reviewer requires for every data-touching path.
