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

## Pipelines & scheduling (in progress)

Pipelines (`source → Iceberg → ClickHouse`) and their run/schedule control bind to
the Dagster control plane (`backend/app/orchestration/`, `docs` in the
orchestration README): the API launches the generic `pipeline_job` by id over
GraphQL, and schedules are owned by the `schedules` registry table + a code-location
reload. The pipeline-job body (dlt load) lands with this work.
