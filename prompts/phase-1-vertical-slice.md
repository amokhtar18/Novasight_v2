# Phase 1 — The first vertical slice

Goal: one CSV flows end to end — upload → Iceberg (tenant namespace) → ClickHouse →
one rendered chart — for a single tenant. This proves every seam.

---

## Task 1.1 — CSV upload endpoint
```
Use the backend-engineer. Follow fastapi-conventions + tenancy-isolation.
Add POST /v1/datasets/upload that accepts a CSV, stores the raw object in the tenant's
MinIO/S3 prefix (derived from TenantContext), and records a Dataset row. Validate file
type and size (limits from settings).
Acceptance: upload returns a dataset id; object lands under the tenant prefix; isolation
test confirms tenant A cannot list tenant B's datasets.
```

## Task 1.2 — dlt pipeline: CSV → Iceberg
```
Use the data-engineer. Follow dbt-dagster-workflow + config-management + tenancy-isolation.
Add a dlt pipeline in backend/app/ingestion that loads an uploaded CSV into an Iceberg
table in the tenant's namespace via the REST catalog. Catalog URI, warehouse, and
credentials come from settings.
Acceptance: running the pipeline creates a tenant-namespaced Iceberg table; re-running
is idempotent.
```

## Task 1.3 — Register the Iceberg table in ClickHouse
```
Use the data-engineer. Follow tenancy-isolation.
Make the Iceberg table queryable from the tenant's ClickHouse database (Iceberg table
engine or a load step). Add a service method to run a read-only, tenant-scoped query.
Acceptance: a SELECT against the dataset returns rows through the tenant's ClickHouse db
only.
```

## Task 1.4 — Query endpoint
```
Use the backend-engineer. Follow fastapi-conventions + tenancy-isolation.
Add POST /v1/datasets/{id}/query that runs a safe, parameterized aggregation (read-only,
row-capped from settings) on a tenant-scoped ClickHouse connection and returns typed
rows.
Acceptance: endpoint returns aggregated data; isolation test confirms no cross-tenant
access; ruff + mypy clean.
```

## Task 1.5 — Frontend: render one chart
```
Use the frontend-engineer.
Scaffold the React app shell (config injected at runtime, no hardcoded URLs). Add an
upload screen and a results screen that calls the query endpoint via TanStack Query and
renders the result with the ECharts-based chart renderer, driven by a chart-spec object.
Acceptance: a user uploads a CSV and sees a chart; tsc + eslint clean. This is the
"it's alive" demo.
```

## Task 1.6 — Slice tests + review
```
Use the test-engineer, then the reviewer.
Add an end-to-end test covering upload → pipeline → query for one tenant, plus the
isolation tests for each new endpoint. Then run /review-changes and address findings.
Acceptance: suite green; reviewer APPROVED.
```
