# Data catalog & lineage — OpenMetadata (Phase 5.3)

Analytica publishes its datasets and end-to-end lineage to **OpenMetadata** so users
can browse a catalog and trace data from raw source to serving table. Ingestion runs
as a Dagster asset at the tail of the pipeline; connection is entirely config-driven.

## Pieces

| Concern | Where | Responsibility |
|---------|-------|----------------|
| Connection | [`settings.py`](../data-platform/orchestration/analytica_orchestration/settings.py) `CatalogSettings` | OM server URL + ingestion JWT + service name from `OPENMETADATA__*`. |
| Ingestion logic | [`catalog.py`](../data-platform/orchestration/analytica_orchestration/catalog.py) | Pure config builders + injected workflow runner + the `catalog_metadata` asset. |
| Server + search | [`infra/compose/docker-compose.yml`](../infra/compose/docker-compose.yml) | `openmetadata-server`, `openmetadata-migrate`, `openmetadata-elasticsearch`. |

## How end-to-end lineage is produced

The `catalog_metadata` asset (downstream of `mart_regional_sales_serving`, so every
table exists) runs two OpenMetadata ingestion stages:

1. **ClickHouse metadata** — registers the tenant's physical tables (the dlt raw
   table, the dbt-built mart, the serving table) under the configured OM service,
   restricted to the tenant's ClickHouse database via a schema filter.
2. **dbt** — reads the dbt `manifest.json` (+ `catalog.json` / `run_results.json`
   when present) to register every dbt model and the model→model lineage
   (staging → intermediate → mart). OpenMetadata stitches the dbt lineage onto the
   physical tables from stage 1.

The result is the full **raw → staging → intermediate → mart → serving** graph,
browsable with column-level lineage when `catalog.json` is present.

## Running it

1. Bring up the stack (OpenMetadata runs migrations, then the server starts):
   ```bash
   docker compose -f infra/compose/docker-compose.yml --env-file .env up -d \
     openmetadata-elasticsearch openmetadata-migrate openmetadata-server
   ```
2. In the OM UI (`http://localhost:8585`), create/copy an **ingestion-bot JWT**
   (Settings → Bots) and set `OPENMETADATA__JWT_TOKEN` + `OPENMETADATA__HOST_PORT`.
3. Materialize the asset: `dagster asset materialize --select catalog_metadata`
   (or run the full job), and browse datasets + lineage in the catalog.

The OpenMetadata ingestion SDK is an **optional** dependency — install it only on the
worker that runs the asset:
```bash
pip install -e 'data-platform/orchestration[catalog]'
```

## Configuration (golden rule 1)

| Var | Meaning |
|-----|---------|
| `OPENMETADATA__HOST_PORT` | OM REST API base, e.g. `http://openmetadata-server:8585/api`. |
| `OPENMETADATA__JWT_TOKEN` | Ingestion-bot JWT used to authenticate to the server. |
| `OPENMETADATA__SERVICE_NAME` | OM service entity name under which ClickHouse is registered. |

ClickHouse connection details are reused from the same `CLICKHOUSE__*` env the rest
of the platform uses — one source of truth. Compose-only port/DB knobs have safe
defaults; see [`.env.example`](../backend/.env.example).

## Tenancy (golden rule 2)

Ingestion is scoped to the tenant's ClickHouse database (`settings.dbt_schema`,
resolved at the boundary) via the schema filter, so the catalog only ever sees this
tenant's tables. `test_catalog.py` asserts the env-driven configs and the
per-tenant scoping (a config for tenant A never references tenant B).

> **Verification note.** The config-building and ingestion logic are unit-tested
> without a live server (the workflow run is injected). Confirming datasets + lineage
> are *visible in the UI* requires the OpenMetadata stack to be running and was not
> exercised in CI.
