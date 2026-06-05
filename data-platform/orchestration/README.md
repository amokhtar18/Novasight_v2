# Analytica orchestration (Dagster)

The Dagster code location for the data platform. Models the world as software-defined
assets so lineage is automatic (see the `dbt-dagster-workflow` skill):

```
regional_sales_raw            dlt ingestion  ->  tenant ClickHouse database (raw source)
  └─ stg_phase1__regional_sales      dbt staging (view)
       └─ int_regional_sales_enriched   dbt intermediate (ephemeral)
            └─ mart_regional_sales         dbt mart (table, validated by the quality gate)
                 └─ mart_regional_sales_serving   loads the validated mart -> serving table
```

- **`ingestion.py`** — the upstream dlt ingestion asset. Publishes the asset key
  `["phase1", "regional_sales"]`, which is the key `dagster-dbt` assigns to the dbt
  `phase1.regional_sales` source, so the graph connects raw → staging → mart.
- **`dbt_assets.py`** — loads the `data-platform/dbt` project via `dagster-dbt`. Every
  model becomes an asset; `dbt build` runs the tests as **blocking asset checks** (the
  quality gate). A failing upstream check makes dbt skip downstream models, so the mart
  is never materialized, and the run fails.
- **`quality_events.py`** — turns each failing asset check into a structured
  `QualityGateFailure` event, emitted as a tenant-scoped `ERROR` log line tagged
  `event_type=quality_gate_failure` for the alerting layer to consume later.
- **`serving.py`** — the downstream serving asset. Promotes the **validated** mart into
  the tenant's ClickHouse serving table (`CREATE OR REPLACE`, so it is atomic and
  re-runnable). Being downstream of the dbt mart asset, it only runs after the quality
  gate passed — an unvalidated mart never reaches the serving surface. A post-load
  asset check (`serving_matches_mart`) verifies the serving table is non-empty and
  row-for-row consistent with the mart.
- **`definitions.py`** — the `Definitions` Dagster loads.

## Quality gate & alerting (Task 2.4)

`dbt build` runs each model then its tests in DAG order. A failing test (surfaced as a
Dagster asset check) stops dbt from building anything downstream — so a bad row caught
at staging blocks the mart from materializing — and the non-zero dbt exit fails the
Dagster run. Every failure also emits a structured event for the (future) reporting
layer; filter the Dagster event log on `event_type=quality_gate_failure`.

```bash
# Unit tests for the gate + event (no warehouse needed):
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m pytest
```

## Serving load (Task 2.5)

After the quality gate passes, `mart_regional_sales_serving` publishes the validated
mart into the tenant's ClickHouse **serving table** (`serving_regional_sales` by
default) — the stable surface the serving / semantic / AI layers read, decoupled from
dbt's internal model name. The load is a server-side `CREATE OR REPLACE TABLE … AS
SELECT` (atomic + re-runnable) scoped to the tenant database, and a post-load asset
check (`serving_matches_mart`) guards against an empty or partial copy. Its logic is
unit-tested with a fake client (`tests/test_serving.py`) — good data, bad data, and
tenant scoping — so no warehouse is needed for the tests.

## Configuration (golden rule 1 — nothing hardcoded)

Everything is read from the environment, using the **same** variables the backend and
the dbt project use. Required before launching:

| Variable                   | Purpose                                                        |
| -------------------------- | ------------------------------------------------------------- |
| `CLICKHOUSE__HOST`         | ClickHouse host (HTTP interface)                              |
| `CLICKHOUSE__PASSWORD`     | ClickHouse password (secret)                                  |
| `DBT_SCHEMA`               | the tenant's dbt schema == its ClickHouse database            |
| `DBT_PHASE1_DATASET_TABLE` | raw source table name (ingestion writes it, dbt source reads it) |

Optional (safe defaults, identical to the backend): `CLICKHOUSE__PORT` (8123),
`CLICKHOUSE__USER` (default), `DBT_THREADS` (4),
`SERVING_REGIONAL_SALES_TABLE` (`serving_regional_sales` — the serving table name).

## Run it locally

```bash
# from data-platform/orchestration, with the venv created and deps installed
#   py -m venv .venv && .venv/Scripts/python -m pip install -e .
# export the env above (same values the backend .env uses), then:
.venv/Scripts/dagster dev
```

Open the UI (default http://localhost:3000), select all assets, and **Materialize** —
this runs the dlt ingestion, then `dbt build` for staging → intermediate → mart with
the tests as asset checks. The Asset lineage view shows raw → staging → mart.
