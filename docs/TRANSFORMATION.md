# Transformation (dbt)

Turns raw, tenant-isolated datasets into modeled, tested marts. Lives in
`data-platform/dbt`, runs against the tenant's **ClickHouse** database, and is
orchestrated per-tenant by Dagster (`dagster-dbt`, Task 2.2). Read the
`dbt-dagster-workflow` skill for the rules; this is the human reference.

## Where it sits

```
dlt -> Iceberg (tenant namespace) -> ClickHouse (tenant db) -> [dbt staging -> intermediate -> marts] -> serving
```

Phase 1 ingests a CSV to the tenant's Iceberg namespace and registers it in the
tenant's ClickHouse database as an Iceberg-engine table (`dataset_<uuid_hex>`). dbt
reads that table as a **source** and builds models in the same tenant database.

## Layering

| Layer | Folder | Materialization | Purpose |
|---|---|---|---|
| staging | `models/staging/` | view | 1:1 with sources; light cleaning + typing only |
| intermediate | `models/intermediate/` | ephemeral | reusable joins / business-logic building blocks |
| marts | `models/marts/` | table | consumption-ready, served by ClickHouse |

One source = one staging model. Every model has at least one test (no untested marts).

### Phase 2.1 staging model

`stg_phase1__regional_sales` (view) cleans and types the Phase 1 sample dataset
(`region`, `amount`; grain = one row per region). Its tests are the first
**data-quality gate**:

- `region` — `not_null` + `unique` (the natural key)
- `amount` — `not_null`

In Task 2.2 these become Dagster **asset checks** that block downstream marts on
failure.

## Quality gate (Dagster asset checks) — Task 2.4

The dbt tests are the pipeline's quality gate. Dagster runs the dbt project with
`dbt build` (not `dbt run`), so models and their tests execute together in DAG order
and every test is surfaced as a Dagster **asset check**
(`data-platform/orchestration/novasight_orchestration/dbt_assets.py`).

**Blocking.** `dbt build` runs each model, then its tests, before anything downstream.
When a test fails, dbt **skips every downstream model** — so a failing *upstream* check
(e.g. a staging `unique`/`not_null`) means the mart is never built. dbt exits non-zero,
which `dagster-dbt`'s `.stream()` re-raises after draining the events, failing the
asset run. Net effect: an unvalidated mart is never materialized or served.

**Observable.** Each failing asset check is turned into a structured
`QualityGateFailure` event (`quality_events.py`) and emitted on a decoupled seam — a
single `ERROR` log line tagged `event_type=quality_gate_failure`, carrying the tenant,
asset key, check name, severity, and failing-row count — for the reporting/alerting
layer to consume later. The producer hardcodes no channel or destination (golden
rule 1) and stamps the tenant resolved at the boundary (golden rule 2).

Verified acceptance: with a duplicate `region` row in the source,
`unique_stg_phase1__regional_sales_region` fails and `mart_regional_sales` is reported
`SKIP` and is not created in ClickHouse; a clean source builds all 17 nodes green.

## Tenant isolation

Both the source and the models resolve to the tenant's ClickHouse database via
`DBT_SCHEMA` (== the tenant's dbt schema, == its ClickHouse db), derived from the
tenant context — never a literal, never from a client. Models carry no custom schema
suffix, so a tenant's models stay in exactly its own schema. See `tenancy-isolation`.

## Configuration (golden rule 1)

`profiles.yml` and `dbt_project.yml` contain **no** hosts, credentials, or
tenant-specific values. The connection is read from the backend's `CLICKHOUSE__*`
environment variables; schema and the source table name come from `DBT_SCHEMA` /
`DBT_PHASE1_DATASET_TABLE` (see `docs/CONFIGURATION.md`). Secrets never live in files.

## Run (dev)

With the local stack up (`make up`) and the env exported (from the repo-root `.env`):

```bash
cd data-platform/dbt
dbt parse --profiles-dir .                       # offline: validates project + profile
dbt build --select staging --profiles-dir .      # builds the staging view + runs its tests
```

`dbt parse` does not connect to ClickHouse. `dbt build` requires the Phase 1 dataset
present in the tenant's ClickHouse database and `DBT_PHASE1_DATASET_TABLE` set to it.

## dbt model + test wizard (#5/#6)

Beyond the static models above, users define **dbt models from the UI** (the
Transforms page, `/transforms`). A definition is a `layer`, a `materialization`, the
model `sql` (a SELECT), and optional column data tests.

- **API** (`backend/app/api/v1/dbt_models.py` → `services/dbt_models.py`):
  `GET/POST /api/v1/dbt-models`, `GET/PATCH/DELETE /api/v1/dbt-models/{id}`. Reads need
  a tenant context; mutations require the tenant superuser role. Names are unique per
  tenant; `layer`/`materialization`/`test_type` are closed sets; the SQL is the user's
  transformation (custom SQL is a first-class dbt path). The wizard exposes all four
  data tests: `not_null`, `unique`, `accepted_values` (a value list) and
  `relationships` (referential integrity — a `to` model ref + `field` column).
- **Codegen** (`backend/app/codegen/dbt_model.py`): the single writer. On every change
  the service re-renders the tenant's enabled models into
  `<DBT__MODELS_DIR>/tenant_<dbt_schema>/` — one `<name>.sql` (with a
  `{{ config(materialized=...) }}` header) plus a `schema.yml` of column/model
  `data_tests`. Stale `.sql` files are pruned on rename/delete. Isolation is by
  directory + the tenant's target schema, mirroring the Cube codegen.
- **Incremental models**: choosing `materialization='incremental'` unlocks an optional
  `incremental` block (schema `IncrementalConfig`): a `unique_key` (one or more column
  identifiers, so runs **upsert** instead of duplicating), an `incremental_strategy`
  (`append`/`merge`/`delete+insert`/`insert_overwrite`), and an `on_schema_change`
  policy (`ignore`/`fail`/`append_new_columns`/`sync_all_columns`). These are closed
  literals + identifiers, so the codegen interpolates them into the `{{ config(...) }}`
  header injection-free; they are stored under the model's `config` JSON (no migration)
  and surfaced back as the typed `incremental` field. The wizard reveals the fields only
  when the materialization is incremental, and the API rejects them otherwise (422).

The pure render + writer are unit-tested (`tests/test_dbt_codegen.py`,
`tests/test_dbt_models_api.py`). Materializing the generated models to ClickHouse runs
via the dynamic Dagster dbt run (#7) and is verified on the running stack; tests become
Dagster asset checks (the existing quality-gate pattern).
