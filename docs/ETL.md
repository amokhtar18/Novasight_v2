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
| `sql_database` | `engine` (a registry key, see below), `host`, `port`, `database`, `username`, `query` | `password` | lists tables; samples a chosen table |
| `filesystem` | `format` (csv/parquet/json/excel), `key` (object key) | — | parses the file head |

Credentials are **never** stored or returned in plaintext: the service envelope-
encrypts the `secret` dict into `source_connections.secret_ciphertext` via
`app.core.crypto`, and decrypts it in-process only to test/preview/run. Storing a
secret therefore requires `ENCRYPTION__*` to be configured (`docs/ENCRYPTION.md`);
without it `POST /sources` with a `secret` returns 400.

The `sql_database` connector talks to the source through a **blocking** SQLAlchemy
engine (run in a worker thread), so it needs a *sync* DBAPI even though the app's own
control-plane access is async (`asyncpg`). A ready-made Postgres source to try the
whole path against lives in `infra/compose/sample-source/` (a seeded e-commerce DB on
the dev stack's Postgres container).

### SQL engine registry (`connectors/engines.py`, #3/#4)

The wizard no longer asks for a raw SQLAlchemy `driver`; it offers an **engine** from a
registry that knows each engine's drivername, standard port, and how its "database"
field reads. `config["engine"]` resolves the drivername (a raw `config["driver"]` still
works as an override, e.g. `sqlite` for tests). These are protocol constants — not
environment/tenant config (golden rule 1 is about the latter); a *connection* supplies
its own host/port/creds.

| engine | label | drivername | port | notes |
|--------|-------|-----------|------|-------|
| `postgres` | PostgreSQL | `postgresql+psycopg2` | 5432 | |
| `mysql` | MySQL | `mysql+pymysql` | 3306 | a "schema" is a database |
| `sqlserver` | SQL Server | `mssql+pymssql` | 1433 | no system ODBC needed |
| `oracle` | Oracle | `oracle+oracledb` | 1521 | thin mode (no Instant Client); "database" = service name |

All four DBAPIs are pure-Python / thin, so the backend image needs no system packages.
`GET /sources/engines` returns the registry (key, label, `default_port`,
`supports_schemas`, `database_label`) so the wizard can render the dropdown and prefill
per-engine defaults. URL construction is split into a pure `_build_url` (drivername +
default-port resolution) so it is unit-testable without that engine's driver installed —
`create_engine` imports the DBAPI eagerly.

## Source-connection API (`/api/v1/sources`)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/sources/kinds` | tenant | connector kinds the wizard offers |
| GET | `/sources/engines` | tenant | SQL engines + per-engine defaults |
| GET | `/sources` / `/sources/{id}` | tenant | list / fetch (tenant-scoped) |
| POST | `/sources` | superuser | create (secret encrypted at rest) |
| PATCH | `/sources/{id}` | superuser | update (omit `secret` to keep it) |
| DELETE | `/sources/{id}` | superuser | delete |
| POST | `/sources/{id}/test` | superuser | connectivity check (422 on failure) |
| POST | `/sources/{id}/preview` | superuser | objects + row sample |
| POST | `/sources/{id}/introspect` | superuser | schema → table → columns drill-down (#5) |

Reads need only a tenant context; mutations and probes require the tenant
`superuser` role (they configure plumbing and reach external systems). The tenant
is resolved from the JWT — never a body/path value (tenancy-isolation).

**Editing (#8).** Sources, pipelines, and schedules are all editable in place from the
Pipelines tab via the existing `PATCH` routes (the create dialogs double as edit dialogs).
Secrets stay **write-only**: the source edit form omits the secret unless a new one is
typed, so a `PATCH /sources/{id}` without `secret` keeps the stored credential. Schedules
can be paused/resumed (a `PATCH` toggling `enabled`) without deleting them.

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
- `GET /pipelines/{id}/runs` — run history for one pipeline (status, rows, timings, error).
- `GET /pipelines/runs?limit=` — **tenant-wide** recent runs across all pipelines, newest
  first, each joined to its `pipeline_name` (the Operations monitoring feed). Declared
  before `/{pipeline_id}` so the literal `runs` segment isn't parsed as an id. Tenant-
  scoped: another tenant's runs are never returned.

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

The UI builds the cron with `components/schedule/CronBuilder.tsx` (#9): a **Preset** mode
turns a frequency (hourly/daily/weekly/monthly) + time into the 5-field expression and shows
a plain-English summary (`describeCron`), while an **Advanced** mode exposes the raw cron for
power users. The builder is pure convenience — the backend still validates the expression.

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

## Operations console (UI)

The `/operations` page (`frontend/src/pages/Operations.tsx`) is the cross-pipeline
control room — what the per-pipeline `/pipelines` view can't give:

- **Schedules** — every cron schedule in the tenant in one list (cron + owning
  pipeline name). A superuser can **pause/resume** (`PATCH /schedules/{id}` flipping
  `enabled`) or delete; non-superusers see a read-only list (the backend enforces the
  role regardless — the UI only hides controls).
- **Recent runs** — the tenant-wide `GET /pipelines/runs` feed, polled every 10s so a
  run's `queued → running → success | error` progress shows live, each row labelled with
  its pipeline name, row count / error, and relative time.

Both surfaces are tenant-scoped through the JWT and reuse the existing schedules /
pipeline-runs APIs (no new write path). Covered by `frontend/src/test/operations.test.tsx`
(empty states, feed rendering, pause flipping `enabled`, superuser gating) and the
backend feed + isolation test in `backend/tests/test_pipelines_api.py`.

## Generic Dagster code location (#7)

The Dagster code location (`data-platform/orchestration/`) is **registry-driven**: it
runs *any* tenant's pipeline or transform by id, with no per-definition Dagster object
and no redeploy. This is the orchestration path that complements the worker dispatch
above (the worker remains the executor; Dagster is the scheduler/launcher of record).

- **Run-config contract** — `backend/app/orchestration/run_config.py` is the source of
  truth for two generic jobs: `pipeline_job` (op `run_pipeline`, config
  `{pipeline_id, tenant}`) and `transform_job` (op `run_transform`, config
  `{transform_job_id, tenant}`). The code location mirrors it in
  `novasight_orchestration/dynamic.py`; `tests/test_dynamic.py` guards the two against
  drift (they are separate deployables and cannot share code).
- **Registry reader** (`novasight_orchestration/registry.py`): the location cannot
  import `backend/app`, so it reads the same control-plane Postgres **directly** with a
  sync driver (`psycopg`), using the identical `POSTGRES__*` env (golden rule 1). Each
  row is joined to `tenants` so it carries its **tenant slug** (golden rule 2) — the
  generic ops resolve the definition for that tenant and never widen scope.
- **Dynamic schedules** (`dynamic.build_schedules`, a pure function): one
  `ScheduleDefinition` per `schedules` row, named deterministically `sched_<uuid hex>`
  (so the backend can address it), cron from the row, and `default_status`
  RUNNING/STOPPED from `enabled`. Unknown `target_kind`s are skipped, not fatal. The
  read is **best-effort** in `definitions.py`: if the database is unreachable the
  location still loads with its jobs/assets (just no dynamic schedules yet).
- **Backend control** (`backend/app/orchestration/dagster_client.py`): `launch_run`
  (run-now → `dagster_run_id`), `reload_location` (after a schedule row changes),
  and `start_schedule` / `stop_schedule` (toggle live state via GraphQL, overriding the
  loaded default). Dagster's stop mutation needs the schedule's origin id, fetched first.

The schedule builder, the run-config contract, the generic-job wiring, and the backend
client are unit-tested (`tests/test_dynamic.py`, `backend/tests/test_dagster_client.py`).
Live launching/scheduling and the `run_transform` dbt build are verified when the stack
is up. `run_pipeline`'s op hands off to the canonical executor (the worker path) at the
documented stack-integration boundary, so run-now and scheduled runs share one ETL impl.

**Still worker-driven today:** the periodiq dispatch (#4) above remains the active
scheduler; switching a deployment to the Dagster schedules is a configuration choice
(don't enable both for the same rows, or they double-fire).
