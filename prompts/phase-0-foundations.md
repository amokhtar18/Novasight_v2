# Phase 0 — Foundations (the skeleton with tenancy baked in)

Goal: a running stack and a backend that already understands settings, auth, and tenant
context — before anything novasightl exists.

---

## Task 0.1 — Local stack with Docker Compose
```
Use the orchestrator to plan, then the backend-engineer.
Create infra/compose/docker-compose.yml with Postgres, Redis, MinIO, and ClickHouse,
matching docs/ARCHITECTURE.md. All credentials, ports, and bucket names come from an
.env file (follow the config-management skill) — none hardcoded in the compose file.
Add a Makefile or README snippet to bring it up and health-check each service.
Acceptance: `docker compose -f infra/compose/docker-compose.yml up -d` starts all four;
health checks for ClickHouse (/ping) and MinIO (/minio/health/live) pass.
```

## Task 0.2 — Typed settings (no hardcoding foundation)
```
Use the backend-engineer. Follow the config-management skill strictly.
Create backend/app/core/config.py with a nested pydantic-settings tree (app,
postgres, redis, minio, clickhouse) and a cached get_settings(). Create .env.example
documenting every variable with comments and placeholder secrets. Create
docs/CONFIGURATION.md listing all variables, their meaning, and which deployment they
vary by.
Acceptance: app boots reading only from env; ruff + mypy clean; no literal infra values
anywhere outside config.py.
```

## Task 0.3 — FastAPI skeleton + health
```
Use the backend-engineer. Follow fastapi-conventions.
Scaffold backend/app with core/, api/v1/, and a /health endpoint that checks DB and
Redis connectivity via injected settings. Wire structured JSON logging (PII-redacted).
Acceptance: GET /health returns component status; uvicorn runs; ruff + mypy clean.
```

## Task 0.4 — Control-plane data model + migrations
```
Use the backend-engineer. Follow fastapi-conventions + config-management.
Add SQLAlchemy models for Tenant, User, and TenantResourceMap (iceberg_namespace,
clickhouse_db, dbt_schema). Create the first Alembic migration. Seed one local tenant
via a script that reads values from settings, not literals.
Acceptance: `alembic upgrade head` builds the schema; seed script creates one tenant;
tenant-isolation test fixtures can create tenants A and B.
```

## Task 0.5 — Auth + tenant context (the core invariant)
```
Use the backend-engineer. Follow the tenancy-isolation skill — this is the most
important task in Phase 0.
Implement OIDC/JWT auth (provider configured via settings; Authentik/Keycloak for
real, a dev stub for local). Implement get_principal and get_tenant_context as
dependencies that resolve the tenant from the authenticated claim via the registry and
fail closed if absent. Derive iceberg_namespace / clickhouse_db / dbt_schema from the
tenant, never from the request.
Acceptance: a protected demo endpoint returns the resolved TenantContext; requests with
no/invalid token are rejected; a test proves a client-supplied tenant id in the body is
ignored. Then run /review-changes.
```
