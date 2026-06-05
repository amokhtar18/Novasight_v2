# Datasets

A **dataset** is one uploaded source object (a CSV today) owned by a single tenant.
This page covers the upload + listing slice (Task 1.1), the CSV-to-Iceberg ingestion
pipeline (Task 1.2), making the Iceberg table queryable through the tenant's
ClickHouse database (Task 1.3), and the aggregation query endpoint (Task 1.4).

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/datasets/upload` | Upload a CSV; stores the raw object and records a `Dataset`. Returns `201` + `DatasetRead`. |
| `GET`  | `/api/v1/datasets` | List the authenticated tenant's datasets only. |
| `POST` | `/api/v1/datasets/{id}/query` | Run a safe, read-only aggregation over one of the tenant's datasets. Returns `200` + `QueryResponse`. |

Both require a valid bearer token. The tenant is resolved from the verified JWT via
`get_tenant_context` — there is **no** tenant id in any request body, query, or path.

### Upload validation
- **File type**: the filename must end in `.csv` (else `415`). CSV is the feature, so this
  is a code constant, not configuration.
- **Size**: capped at `MAX_UPLOAD_MB` (default 100) from settings; oversized uploads are
  rejected with `413` and nothing is stored. The body is read in chunks so we never buffer
  more than the limit.
- Empty filename / empty body → `400`.

## Storage layout (tenant isolation)

The raw bytes live in the configured S3-compatible bucket (`OBJECT_STORE__*`). The object
key is derived entirely server-side from the tenant context — never the client:

```
<iceberg_namespace>/raw/datasets/<dataset_id>/<safe_filename>
```

The tenant's object-store prefix **is** its Iceberg namespace (the same isolation boundary
per `docs/ARCHITECTURE.md`). Because namespaces are globally unique in the
`tenant_resource_maps` registry, two tenants can never share a prefix. The
`datasets.tenant_id` column is the isolation key for every read; `list_datasets` filters on
it, so one tenant can never list another's datasets.

## Object store seam

`app/core/object_store.py` exposes an `ObjectStore` Protocol and an aioboto3-backed
`S3ObjectStore`. The bucket and credentials come from `ObjectStoreSettings`, bound once at
construction; callers only ever pass a key, so they cannot reach another bucket. Tests
substitute an in-memory fake via `dependency_overrides` — no live MinIO/S3 needed.

## Components (Task 1.1 — upload/listing)

| Layer | File |
|---|---|
| Router (thin) | `app/api/v1/datasets.py` |
| Service (validation, storage, scoping) | `app/services/datasets.py` |
| ORM model | `app/models/dataset.py` (migration `0002_datasets`) |
| Response schema | `app/schemas/dataset.py` |
| Object store adapter | `app/core/object_store.py` |

---

## Iceberg ingestion pipeline (Task 1.2)

`CsvIcebergPipeline` in `app/ingestion/csv_iceberg.py` loads an uploaded CSV into an
Apache Iceberg table in the tenant's Iceberg namespace via the REST catalog.

### What it does

1. Downloads raw CSV bytes from the object store via `ObjectStore.get_object`.
2. Parses the CSV to an Apache Arrow table (schema inferred from headers + values).
3. Opens a pyiceberg `RestCatalog` built entirely from `Settings` — no literals, no
   config files written at runtime.
4. Creates the tenant's Iceberg namespace if it does not exist (idempotent).
5. Creates the Iceberg table on first run; **overwrites** on subsequent runs.

### Idempotency

The write strategy is `Table.overwrite()` with a **deterministic table name** derived
from the dataset id:

```
dataset_<uuid_hex>   (hyphens stripped — valid SQL identifier)
```

Re-running the pipeline on the same dataset atomically replaces all data files in the
table, producing exactly the same state as the first run. No duplicate rows accumulate.

### Tenant isolation

The Iceberg namespace is taken verbatim from `TenantContext.iceberg_namespace`, which
is resolved server-side from the authenticated JWT.  The pipeline constructor does not
accept a namespace from callers.  `run()` enforces that `dataset.tenant_id` matches
the pipeline's own `TenantContext.tenant_id`, raising `ValueError` otherwise.

### Qualified table identifier

`run()` returns the string `<namespace>.<table_name>` — e.g. `acmecorp.dataset_abc123...`.

### Why pyiceberg directly (not dlt filesystem destination's Iceberg path)

dlt's `filesystem` destination with `table_format="iceberg"` resolves the catalog via
its own `@with_config` injection chain, which reads from `.pyiceberg.yaml` or
`secrets.toml`. Writing those files at runtime would violate golden rule 1 (no
infra-specific values outside `config.py`). Instead, pyiceberg's `load_catalog` is
called with a properties dict built directly from `Settings`. `dlt` is retained in
`pyproject.toml` for future use in streaming/incremental loads (see `dbt-dagster-workflow`
skill: dlt is the preferred declarative ingestion layer).

### Object store seam extension

`ObjectStore` (and `S3ObjectStore`) gained a `get_object(key)` method to support
downloading raw bytes — symmetric with `put_object`. Fakes and tests implement it.

### Components (Task 1.2 — ingestion)

| Layer | File |
|---|---|
| Pipeline class + assembler | `app/ingestion/csv_iceberg.py` |
| Package init | `app/ingestion/__init__.py` |
| Object store (extended) | `app/core/object_store.py` — added `get_object` |
| Settings (extended) | `app/core/config.py` — added `IcebergSettings.catalog_token` |
| Iceberg catalog helper | `app/core/iceberg_catalog.py` — shared catalog construction |

---

## Querying via ClickHouse (Task 1.3)

`ClickHouseDatasetService` in `app/services/clickhouse_datasets.py` makes a tenant's
Iceberg dataset queryable from that tenant's ClickHouse database and runs read-only,
tenant-scoped queries against it.

### Registration (Iceberg table engine)

`register_dataset(ctx, dataset)`:

1. Asserts the dataset belongs to the context tenant (fail closed otherwise).
2. Resolves the Iceberg table's **physical location from the catalog** (the source of
   truth — not a hand-built path) via the shared `app/core/iceberg_catalog.py` helper.
3. `CREATE DATABASE IF NOT EXISTS <clickhouse_db>` — the tenant's serving database.
4. `CREATE TABLE IF NOT EXISTS <clickhouse_db>.<table> ENGINE = IcebergS3(<url>, …)` —
   an Iceberg-engine table that reads the lake files **in place** (no second copy to
   keep in sync). The S3 URL is derived from the catalog location + the configured
   object-store endpoint; the engine's S3 credentials come from `OBJECT_STORE__*`.

Both DDL statements use `IF NOT EXISTS`, so re-registration is idempotent. The table
name mirrors the Iceberg table name (`dataset_<uuid_hex>`). Returns the fully-qualified
`<clickhouse_db>.<table>` identifier.

> **Why the Iceberg engine over a load/copy step?** ClickHouse reads the Iceberg table
> directly from object storage, so the serving layer queries the same files the lake
> holds — no ETL copy, no drift. The task allowed either; this keeps the slice thin.

### Read-only, tenant-scoped queries

- `run_read_only_query(ctx, sql)` — runs `sql` with the connection **bound to
  `ctx.clickhouse_db`** and ClickHouse's `readonly` setting on. An unqualified table
  can only resolve inside the tenant's own database, and writes are rejected.
- `fetch_sample(ctx, dataset, limit=…)` — convenience that `SELECT`s from the
  tenant-scoped table (limit defaults to `DEFAULT_PAGE_SIZE` from settings). This is
  the Task 1.3 acceptance: a `SELECT` against the dataset returns rows through the
  tenant's ClickHouse database only.

### Tenant isolation

The ClickHouse database name is `TenantContext.clickhouse_db`, resolved server-side
from the JWT — never a caller parameter. The `ClickHouseClient.query` boundary
**requires** a database and opens the connection against it, so isolation holds at the
connection level. Cross-tenant datasets are rejected before any statement is issued.

### ClickHouse seam

`app/core/clickhouse.py` exposes a `ClickHouseClient` Protocol and a
`clickhouse-connect`-backed `ConnectClickHouseClient`. Host/port/credentials come from
`ClickHouseSettings` (`CLICKHOUSE__*`); callers pass only SQL + a database. Tests
substitute an in-memory fake — no live ClickHouse needed.

### Components (Task 1.3 — ClickHouse serving)

| Layer | File |
|---|---|
| Registration + query service | `app/services/clickhouse_datasets.py` |
| ClickHouse client seam | `app/core/clickhouse.py` |
| Shared Iceberg catalog helper | `app/core/iceberg_catalog.py` |
| Tests (incl. isolation) | `tests/test_clickhouse_datasets.py` |

---

## Aggregation query endpoint (Task 1.4)

`POST /api/v1/datasets/{id}/query` runs a **structured** aggregation over one of the
tenant's datasets and returns typed rows. The request describes an aggregation — it is
never free SQL — which is what makes it safe:

```jsonc
{
  "dimensions": ["region"],                                  // GROUP BY columns
  "metrics": [{ "function": "sum", "column": "amount",
               "alias": "total" }],                          // ≥ 1 required
  "filters": [{ "column": "active", "op": "=", "value": true }],
  "limit": 500                                               // optional; clamped
}
```

Response (`QueryResponse`): ordered `columns`, `rows` (list of value lists), and
`row_count`. With no `dimensions` the result is a single global-aggregate row.

### Safety (golden rule 3 — read-only, validated)

- **Identifiers** (dimension/metric columns and aliases) are constrained to
  `^[A-Za-z_]\w*$` at the Pydantic boundary, so anything with SQL metacharacters is
  rejected with `422` before any SQL is built — and the builder still backtick-quotes
  them defensively.
- **Functions** (`count|sum|avg|min|max`) and **operators** (`=|!=|<|<=|>|>=`) are
  closed `Literal` sets. `count` may omit a column (`count(*)`); every other function
  requires one (`422` otherwise).
- **Filter values** are bound as ClickHouse **server-side parameters** (`{p0:Type}`),
  never interpolated into the SQL text. The CH type is derived from the Python value
  (`bool`→`Bool`, `int`→`Int64`, `float`→`Float64`, else `String`).
- **Row cap**: the effective `LIMIT` is `min(request.limit, MAX_QUERY_ROWS)` from
  settings — never a literal, and a caller cannot exceed the platform maximum.
- The query runs through `run_read_only_query`, bound to the tenant's ClickHouse
  database with `readonly` on.

### Tenant isolation

Two independent guards, both server-side:

1. **Control plane** — `DatasetService.get_for_tenant(ctx, id)` filters on
   `tenant_id` as well as the id. A dataset owned by another tenant is
   indistinguishable from one that doesn't exist: both return `404`, with **no query
   issued to ClickHouse** (no existence leak, fail closed).
2. **Serving plane** — the compiled `SELECT` runs bound to `ctx.clickhouse_db`, so even
   a resolved table can only be the caller's own.

The `{id}` in the path is the only client-supplied identifier and is always resolved
within the tenant scope; there is no tenant id in the body.

### Components (Task 1.4 — query endpoint)

| Layer | File |
|---|---|
| Router endpoint (thin) | `app/api/v1/datasets.py` — `query_dataset` |
| Request/response schemas | `app/schemas/query.py` |
| Tenant-scoped dataset lookup | `app/services/datasets.py` — `get_for_tenant` |
| Aggregation builder + run | `app/services/clickhouse_datasets.py` — `run_aggregation` |
| Tests (incl. isolation) | `tests/test_dataset_query` cases in `tests/test_datasets.py` + `tests/test_clickhouse_datasets.py` |
