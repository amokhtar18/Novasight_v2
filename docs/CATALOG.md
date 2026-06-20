# Data catalog & lineage — OpenMetadata (Phase 5.3)

NovaSight publishes every tenant's datasets and **end-to-end lineage** to
**OpenMetadata** so users can browse a catalog and trace data from raw source all the
way to the governed semantic layer. Ingestion runs as Dagster jobs/assets at the tail
of the pipeline; the connection and every service name are config-driven.

Coverage is **per-tenant and registry-driven**: the single static `catalog_metadata`
asset catalogs the on-prem boundary tenant, while a generic `catalog_job` catalogs
*any* tenant by slug, and a nightly **refresh schedule** is built for every provisioned
tenant — so the whole platform stays catalogued, not just the demo pipeline.

## Pieces

| Concern | Where | Responsibility |
|---------|-------|----------------|
| Connection + service names | [`settings.py`](../data-platform/orchestration/novasight_orchestration/settings.py) `CatalogSettings` / `IcebergSettings` | OM server URL + ingestion JWT, the OM service names, the refresh cron, and the Iceberg REST catalog — all from `OPENMETADATA__*` / `ICEBERG__*`. |
| Metadata ingestion | [`catalog.py`](../data-platform/orchestration/novasight_orchestration/catalog.py) | Pure per-stage config builders (ClickHouse, Iceberg, dbt) + injected workflow runner + the `catalog_metadata` asset. |
| Cross-system lineage | [`catalog_lineage.py`](../data-platform/orchestration/novasight_orchestration/catalog_lineage.py) | Pure edge builders (`source → Iceberg → ClickHouse → Cube`) from registry rows + injected emitter. |
| Isolated OM-SDK runner | [`catalog_om_runner.py`](../data-platform/orchestration/novasight_orchestration/catalog_om_runner.py) | Runs OM ingestion workflows + posts lineage in a **separate venv** (`/opt/om-venv`) the catalog code shells out to — the SDK can't share the dbt/dagster venv. |
| Per-tenant job + schedules | [`dynamic.py`](../data-platform/orchestration/novasight_orchestration/dynamic.py) | The generic `catalog_job` (run any tenant by slug) and `build_catalog_schedules` (one refresh per tenant). |
| Registry reads | [`registry.py`](../data-platform/orchestration/novasight_orchestration/registry.py) | Resolves a tenant's scope (ClickHouse DB + Iceberg namespace) and its pipelines / semantic models, joined to the tenant at the boundary. |
| Server + search | [`infra/compose/docker-compose.yml`](../infra/compose/docker-compose.yml) | `openmetadata-server`, `openmetadata-migrate`, `openmetadata-elasticsearch`. |
| In-app access | [`nav.ts`](../frontend/src/components/layout/nav.ts) + [`config.ts`](../frontend/src/lib/config.ts) | A **"Data Catalog"** sidebar link that opens the OM UI when `catalogUrl` is configured. |

## How end-to-end lineage is produced

For one tenant the catalog run executes these stages, each scoped to that tenant's
data surfaces (golden rule 2):

1. **ClickHouse metadata** — registers the tenant's physical tables (the dlt raw table,
   the dbt-built mart, the serving table), restricted to the tenant's ClickHouse
   database via a schema filter.
2. **Iceberg metadata** — registers the tenant's lake (landing) tables via the Iceberg
   REST catalog, restricted to the tenant's Iceberg namespace. *(Run only when the scope
   carries a namespace — i.e. the registry-driven path.)* This stage is **best-effort**:
   OpenMetadata's Iceberg connector is immature (a non-discriminated catalog union that
   mis-routes REST to Hive), so a scan failure is logged and skipped — the lake tables
   are still created and linked by the lineage stage below, so the hop never disappears.
3. **dbt** — reads the dbt `manifest.json` (+ `catalog.json` / `run_results.json` when
   present) to register every dbt model and the model→model lineage (staging →
   intermediate → mart), with column-level lineage when `catalog.json` is present.
4. **Cross-system lineage** — from the tenant's own registry rows, stitches the edges
   dlt and Cube don't emit: per pipeline `source object → Iceberg table → ClickHouse
   table`, and per semantic model `ClickHouse base table → Cube cube`. Metadata only —
   no source credentials are touched.

The result is the full **source → Iceberg → ClickHouse → dbt → Cube** graph, browsable
in the OpenMetadata UI.

## Running it

1. Bring up the stack (OpenMetadata runs migrations, then the server starts):
   ```bash
   docker compose -f infra/compose/docker-compose.yml --env-file .env up -d \
     openmetadata-elasticsearch openmetadata-migrate openmetadata-server
   ```
   (`--env-file .env` is required — Compose anchors `.env` to the compose file's dir.)
2. In the OM UI (`http://localhost:8585`), create/copy an **ingestion-bot JWT**
   (Settings → Bots) and set `OPENMETADATA__JWT_TOKEN` + `OPENMETADATA__HOST_PORT`.
3. Catalog a tenant:
   - **Demo / single tenant:** `dagster asset materialize --select catalog_metadata`.
   - **Any tenant (registry-driven):** launch `catalog_job` with run config
     `{"ops": {"run_catalog": {"config": {"tenant": "<slug>"}}}}` (the backend launches
     it via the Dagster GraphQL client; see [`run_config.py`](../backend/app/orchestration/run_config.py)).
   - **Automatic:** every provisioned tenant gets a nightly refresh schedule
     (`OPENMETADATA__REFRESH_CRON`, default `0 2 * * *`).
4. Browse datasets + lineage in the catalog. To reach it from inside NovaSight, set
   `catalogUrl` in the frontend's `public/config.js` (e.g. `http://localhost:8585`) — a
   **"Data Catalog"** link then appears in the sidebar.

The OpenMetadata ingestion SDK **cannot share a venv** with the dagster/dbt stack — it
collides with `dbt-clickhouse` on `dbt-adapters` (the only overlapping version is
yanked). So building the Dagster image with `--build-arg INSTALL_CATALOG=true` installs
the SDK (`openmetadata-ingestion[clickhouse,iceberg,dbt]`) into a **dedicated venv**
(`/opt/om-venv`); the catalog code shells out to it via `catalog_om_runner.py`. The main
venv never imports the SDK, so the code location and its unit tests load without it.
For a standalone local SDK, `pip install -e 'data-platform/orchestration[catalog]'` into
a *clean* venv (not the dagster one).

## Configuration (golden rule 1)

| Var | Meaning |
|-----|---------|
| `OPENMETADATA__HOST_PORT` | OM REST API base, e.g. `http://openmetadata-server:8585/api`. |
| `OPENMETADATA__JWT_TOKEN` | Ingestion-bot JWT used to authenticate to the server. |
| `OPENMETADATA__SERVICE_NAME` | OM service for ClickHouse (default `novasight_clickhouse`). |
| `OPENMETADATA__ICEBERG_SERVICE_NAME` | OM service for the Iceberg lake (default `novasight_iceberg`). |
| `OPENMETADATA__SOURCE_SERVICE_NAME` | OM service for upstream sources (default `novasight_sources`). |
| `OPENMETADATA__SEMANTIC_SERVICE_NAME` | OM service for Cube cubes (default `novasight_semantic`). |
| `OPENMETADATA__REFRESH_CRON` | Cron for the per-tenant refresh schedules (default `0 2 * * *`). |
| `ICEBERG__CATALOG_URI` / `ICEBERG__WAREHOUSE` / `ICEBERG__CATALOG_TOKEN` | Iceberg REST catalog — the **same** env the backend writer uses. |
| `catalogUrl` (frontend `config.js`) | Public OM UI URL for the in-app "Data Catalog" link. |

ClickHouse and Iceberg connection details are reused from the same `CLICKHOUSE__*` /
`ICEBERG__*` env the rest of the platform uses — one source of truth.

## Tenancy (golden rule 2)

Each run resolves the tenant's scope (ClickHouse database + Iceberg namespace) from its
`tenant_resource_maps` row at the boundary; every ingestion stage is filtered to that
namespace/database, and every lineage endpoint is addressed within the tenant's own
surfaces — so the catalog only ever sees this tenant's data. `test_catalog.py`,
`test_catalog_lineage.py`, and `test_dynamic.py` assert the env-driven configs, the
per-tenant scoping (a config/edge for tenant A never references tenant B), and the
generic job + schedule wiring.

> **Verification.** The config/edge builders and job wiring are unit-tested without a
> live server (ingestion + lineage emission are injected). The end-to-end path was also
> **live-verified** against the running stack for tenant `local` (2026-06-19): the 6
> ClickHouse tables registered under `novasight_clickhouse`, and the OM API returned the
> full lineage — `novasight_sources…orders → novasight_iceberg…orders →
> novasight_clickhouse…orders` and `novasight_clickhouse…category_sales →
> novasight_semantic…category_revenue` (logical `CustomDatabase` services for the
> source / lake / semantic sides are created by the lineage stage). The Iceberg *scan*
> is best-effort (immature OM connector); the lineage stage still creates the lake hop.
