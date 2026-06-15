# Sample source database

A throwaway **source system** for exercising the `sql_database` ingestion pipeline
(`docs/ETL.md`). It stands in for a customer's operational database: a small,
realistic e-commerce schema the connector can list, preview, and extract from.

It lives in its **own database** (`nova_sample_source`) on the same Postgres
container as the control plane — purely for dev convenience. It is *not* part of
NovaSight's control plane and nothing in the app reads it directly; the connector
reaches it over the network exactly as it would a real external source.

## Schema

| table | rows | notes |
|-------|------|-------|
| `customers`   |   200 | id, name, email, country, signup_date |
| `products`    |    40 | id, name, category, price |
| `orders`      | 1,000 | FK → customers; status, total_amount (rolled up from items) |
| `order_items` | 2,500 | FK → orders, products; quantity, unit_price |

## (Re)create it

`seed.sql` is idempotent (drops + rebuilds the tables, so row counts are
deterministic). With the stack up (`infra/compose/README.md`):

```bash
# create the database (no-op if it already exists)
docker exec compose-postgres-1 sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tc \
   "SELECT 1 FROM pg_database WHERE datname='\''nova_sample_source'\''" | grep -q 1 \
   || psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "CREATE DATABASE nova_sample_source"'

# load the schema + data
docker exec -i compose-postgres-1 sh -c \
  'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d nova_sample_source' \
  < infra/compose/sample-source/seed.sql
```

## Point a source connection at it

Create a `sql_database` source connection (ETL wizard or `POST /api/v1/sources`)
with this **config** (reach Postgres by its compose service name from inside the
stack, not `localhost`):

```jsonc
{
  "name": "Sample Postgres (nova_sample_source)",
  "kind": "sql_database",
  "config": {
    "driver": "postgresql",   // sync SQLAlchemy dialect; image bundles psycopg2
    "host": "postgres",       // compose service name (in-network)
    "port": 5432,
    "database": "nova_sample_source",
    "username": "<POSTGRES__USER from .env>"
  },
  "secret": { "password": "<POSTGRES__PASSWORD from .env>" }
}
```

Then build a pipeline selecting an object (e.g. `"object": "orders"`) and a
`target_table`; run it to land `source → Iceberg → ClickHouse`.

## Two deployment requirements this surfaced

- **Sync Postgres driver.** The `sql_database` connector uses a *blocking*
  SQLAlchemy engine, so it needs a sync DBAPI (the app's own access is async via
  `asyncpg`). The backend image now bundles `psycopg2-binary` (`backend/pyproject.toml`).
- **Encryption must be configured.** Storing a source's credential requires
  `ENCRYPTION__*` (see `docs/ENCRYPTION.md`); without it `POST /api/v1/sources` with a
  `secret` returns **400** ("Encryption is not configured"). Set `ENCRYPTION__PROVIDER`
  and `ENCRYPTION__KEY` in the root `.env` to use the wizard/API credential path.
