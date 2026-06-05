# Phase 6 — Scale out

Goal: the cloud-native multi-tenant deployment and UX polish, from the same codebase.

---

## Task 6.1 — Containerize for production
```
Use the backend-engineer + data-engineer.
Write production Dockerfiles (multi-stage, non-root) for the API, workers, and Dagster.
All runtime config via env; no build-time secrets.
Acceptance: images build and run reading config from the environment only.
```

## Task 6.2 — Helm charts
```
Use the backend-engineer.
Author infra/helm charts for the API, workers, Dagster, and dependencies, with values
files for onprem (single-tenant) and cloud (multi-tenant). The single difference is
configuration + storage backend (MinIO vs S3), per the architecture's portability seam.
Acceptance: `helm template` renders both profiles; no hardcoded infra in templates.
```

## Task 6.3 — Tenant provisioning automation
```
Use the backend-engineer. Follow tenancy-isolation.
Add a control-plane provisioning flow that, for a new tenant, creates the Iceberg
namespace, ClickHouse database, dbt schema, and registry entry atomically.
Acceptance: provisioning a tenant yields a fully isolated, queryable environment;
de-provisioning cleans up.
```

## Task 6.4 — Observability
```
Use the backend-engineer.
Wire Prometheus metrics, Grafana dashboards, and OpenTelemetry tracing across API,
workers, and pipelines (endpoints/exporters via settings).
Acceptance: request, pipeline, and resource metrics are visible; traces span a request
end to end.
```

## Task 6.5 — Low-code UX polish + review
```
Use the frontend-engineer, then reviewer.
Refine the builder and exploration UX (templates, onboarding, empty states, AI prompts
surfaced contextually). Run /review-changes.
Acceptance: a non-technical user can connect data, build a dashboard, and ask a
question without help; reviewer APPROVED.
```
