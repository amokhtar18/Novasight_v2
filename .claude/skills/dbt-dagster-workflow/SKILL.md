---
name: dbt-dagster-workflow
description: >
  How transformation and orchestration fit together in NovaSight. Apply when creating
  or editing dbt models/tests or Dagster assets, jobs, schedules, and asset checks in
  data-platform/. Covers the raw→staging→marts layering, quality gates as asset checks,
  and per-tenant scoping.
---

# dbt + Dagster workflow

## Layering (dbt)
```
models/
  staging/     # 1:1 with sources, light cleaning, renamed columns, typed
  intermediate/# reusable joins / business logic building blocks
  marts/       # consumption-ready tables loaded into ClickHouse
```
- One source = one staging model. Marts are what the semantic layer and serving engine
  read.
- Every model has at least one test: `unique`, `not_null`, relationship, or a
  `dbt-expectations` check. No untested marts.
- No credentials or hostnames in dbt files — use the env-driven `profiles.yml` target.
  Schema/target is derived from the tenant context (see `tenancy-isolation`).

## Orchestration (Dagster)
- Model the world as **software-defined assets**: Iceberg tables and dbt models are
  assets; lineage is then automatic.
- Load dbt as assets via `dagster-dbt` so dbt models appear in the Dagster asset graph.
- Wrap dbt tests / data-quality checks as **asset checks**. A failing check blocks
  downstream materialization and raises an alert (hand the alert to `reporting`).
- Schedules and sensors (event-triggered loads) live in
  `data-platform/orchestration`. Keep them declarative.

## The standard pipeline shape
1. `dlt` ingests source → Iceberg table in the tenant namespace (asset).
2. dbt staging → intermediate → mart (assets), each with tests as asset checks.
3. Quality gate (asset checks) must pass.
4. Mart loaded into the tenant's ClickHouse database for serving (asset).

## Rules
- Idempotent and re-runnable; prefer incremental models with clear unique keys.
- Quality gate before serving — never expose an unvalidated mart.
- Everything tenant-scoped: namespace, schema, and database derive from context.

Validate: `dbt parse`, then `dbt build --select <model>+` against the dev target;
in Dagster, materialize the asset and confirm checks pass.
