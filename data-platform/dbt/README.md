# Analytica dbt project

Transforms raw, tenant-isolated datasets into modeled, tested marts. Runs against the
tenant's **ClickHouse** database; orchestrated per-tenant by Dagster (`dagster-dbt`,
Task 2.2). See `docs/TRANSFORMATION.md` and the `dbt-dagster-workflow` skill.

## Layering

```
models/
  staging/       1:1 with sources, light cleaning + typing   -> view
  intermediate/  reusable joins / business logic             -> ephemeral
  marts/         consumption-ready, loaded into ClickHouse    -> table
```

## Configuration (no secrets in files — golden rule 1)

Connection and schema come entirely from the environment, reusing the backend's
`CLICKHOUSE__*` variables (config-management). Required / optional env:

| Env var | Required | Meaning |
|---|---|---|
| `CLICKHOUSE__HOST` | yes | Serving-engine host |
| `CLICKHOUSE__PASSWORD` | yes | Serving-engine password (secret) |
| `DBT_SCHEMA` | yes | Tenant dbt schema == tenant ClickHouse database (from tenant context) |
| `DBT_PHASE1_DATASET_TABLE` | for `build` | Registered Phase 1 dataset table (`dataset_<uuid_hex>`) |
| `CLICKHOUSE__PORT` | no (8123) | HTTP port |
| `CLICKHOUSE__USER` | no (default) | User |
| `DBT_THREADS` | no (4) | dbt threads |

`DBT_SCHEMA` and `DBT_PHASE1_DATASET_TABLE` are **tenant/runtime data**, resolved from
the tenant context at invocation — never literals in the repo.

## Run (dev)

`profiles.yml` lives in this directory; point dbt at it with `--profiles-dir .`
(or export `DBT_PROFILES_DIR`). With the env above exported:

```bash
dbt parse --profiles-dir .
dbt build --select staging --profiles-dir .
```

`dbt parse` does not connect to ClickHouse. `dbt build` requires the local stack up
(`make up`) and the Phase 1 dataset present in the tenant's ClickHouse database.
