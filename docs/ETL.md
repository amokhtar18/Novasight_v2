# ETL — sources, connectors & pipelines

NovaSight's ETL wizard lets a tenant superuser connect a source, preview it, and
(next) build a pipeline that lands data as Iceberg in the lake and registers it to
ClickHouse — all from the UI, scheduled via Dagster.

## Connectors (`backend/app/ingestion/connectors/`)

A connector is the seam between a source *kind* and how we talk to it. Each one
validates its config, tests connectivity, and previews objects/rows. IO methods are
async (blocking work runs in a worker thread). Add a connector = new module + one
branch in `connectors/__init__.py::build_connector` (the `kind` is a plain string —
no migration).

| kind | config (non-secret) | secret | preview |
|------|---------------------|--------|---------|
| `sql_database` | `driver` (SQLAlchemy dialect), `host`, `port`, `database`, `username`, `query` | `password` | lists tables; samples a chosen table |
| `filesystem` | `format` (csv/parquet/json/excel), `key` (object key) | — | parses the file head |

Credentials are **never** stored or returned in plaintext: the service envelope-
encrypts the `secret` dict into `source_connections.secret_ciphertext` via
`app.core.crypto`, and decrypts it in-process only to test/preview/run.

## Source-connection API (`/api/v1/sources`)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/sources/kinds` | tenant | connector kinds the wizard offers |
| GET | `/sources` / `/sources/{id}` | tenant | list / fetch (tenant-scoped) |
| POST | `/sources` | superuser | create (secret encrypted at rest) |
| PATCH | `/sources/{id}` | superuser | update (omit `secret` to keep it) |
| DELETE | `/sources/{id}` | superuser | delete |
| POST | `/sources/{id}/test` | superuser | connectivity check (422 on failure) |
| POST | `/sources/{id}/preview` | superuser | objects + row sample |

Reads need only a tenant context; mutations and probes require the tenant
`superuser` role (they configure plumbing and reach external systems). The tenant
is resolved from the JWT — never a body/path value (tenancy-isolation).

## Pipelines (#3)

A **pipeline** binds a saved source connection to a selection (which table/object to
read) and a target Iceberg table, then lands data `source → Iceberg → ClickHouse`.

### API (`backend/app/api/v1/pipelines.py`)

Reads (`GET /pipelines`, `GET /pipelines/{id}`, `GET /pipelines/{id}/runs`) need a
tenant context. Mutations and **run-now** require the tenant superuser role.

- `POST /pipelines` — create (the source connection must belong to the tenant).
- `PATCH`/`DELETE /pipelines/{id}` — update / delete.
- `POST /pipelines/{id}/run` — **202**: records a `queued` PipelineRun and enqueues a
  worker; returns the run. A disabled pipeline returns 409.
- `GET /pipelines/{id}/runs` — run history (status, rows, timings, error).

A pipeline (or its source) from another tenant is indistinguishable from not-found
(404). Implementation: `services/pipelines.py` (enqueue is injectable so the request
path imports without a broker; tests verify enqueue without one).

### Execution (off the request path)

`run-now` enqueues the `run_pipeline` Dramatiq actor (`ingestion/actors.py`), which
runs the `PipelineExecutor` (`ingestion/pipeline_executor.py`):

1. re-resolve the tenant scope from the registry (`resolve_tenant_context_for_job`);
2. `extract` — the connector reads the selected object into an Arrow table
   (`SourceConnector.extract`);
3. `load` — write/overwrite the tenant's Iceberg landing table
   (`ingestion/iceberg_writer.write_arrow_table`, shared with CSV upload);
4. `register` — create the `IcebergS3` table in the tenant's ClickHouse DB
   (`ClickHouseDatasetService.register_table`).

The run walks `queued → running → success | error`, recording rows/timings/error. The
executor's **steps are injected**, so the orchestration + lifecycle are fully unit-
tested (`tests/test_pipeline_executor.py`) with no infra; the concrete extract/load/
register adapters are thin and verified against the running stack.

## Schedules (#4)

A **schedule** binds a cron to a pipeline so it runs on a cadence — no Dagster needed
(consistent with run-now going through the worker). Schedules are tenant config.

- **API** (`backend/app/api/v1/schedules.py` → `services/schedules.py`):
  `GET/POST /api/v1/schedules`, `GET/PATCH/DELETE /api/v1/schedules/{id}`. Reads need a
  tenant context; mutations require the tenant superuser role. The cron is validated at
  the schema boundary (5-field matcher, `app/reporting/cron.py`); the target pipeline
  must belong to the tenant. `target_kind` is `pipeline` (scheduling dbt transforms
  arrives with the dbt run path).
- **Dispatch** (`backend/app/ingestion/scheduler.py`): a periodiq actor
  `dispatch_due_pipelines` fires on `PIPELINE_DISPATCH_CRON` (every minute by default),
  then `ScheduleService.create_due_runs` records a queued run + enqueues `run_pipeline`
  for each enabled schedule whose cron is due (skipping disabled pipelines). Reading the
  schedule registry is control-plane; each enqueued run re-resolves its own tenant scope.

The due-selection + run-creation logic is unit-tested (`tests/test_schedules_api.py`);
the periodiq heartbeat runs in the worker (registered in `app/reporting/worker.py`).

UI: each pipeline row on `/pipelines` has a **Schedule** action (add cron schedules /
delete them) and shows a *scheduled* badge.

**Remaining (later slices):** routing pipeline/transform orchestration through the
dynamic Dagster code location (#7 — `dagster_run_id` stays null for worker runs today),
and scheduling dbt transforms (needs the dbt run path).
