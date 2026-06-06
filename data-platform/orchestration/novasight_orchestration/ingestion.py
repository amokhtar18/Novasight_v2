"""Raw dlt ingestion as the upstream Dagster asset.

This is the head of the pipeline (dbt-dagster-workflow skill, step 1: "dlt ingests
source -> table in the tenant namespace (asset)"). It publishes the asset key
``["phase1", "regional_sales"]`` — the exact key ``dagster-dbt`` assigns to the dbt
`phase1.regional_sales` source — so the asset graph connects:

    regional_sales_raw (this asset)
        -> stg_phase1__regional_sales -> int_regional_sales_enriched -> mart_regional_sales

## Why dlt for extract + a direct client for the write

This mirrors the pattern the canonical ingestion already documents
(``backend/app/ingestion/csv_iceberg.py``): **dlt is the declarative resource /
schema layer; a direct client performs the physical write.** In production that write
target is Apache Iceberg via the REST catalog (``CsvIcebergPipeline``). The local dev
compose stack exposes ClickHouse over its HTTP interface only (port 8123) and runs no
Iceberg catalog, and dlt's ClickHouse destination requires the native protocol
(port 9000). So here the dlt-extracted records are written to the tenant's ClickHouse
database over the same HTTP seam the backend uses — the database dbt then reads as its
source. The dlt extraction layer is identical across both targets.

## Configuration & tenancy

Every infra value comes from the environment via ``OrchestrationSettings`` (golden
rule 1): no hosts, ports, credentials, schema, or table names are hardcoded. The write
is scoped to the tenant's ClickHouse database (``settings.dbt_schema``), resolved at
the boundary — golden rule 2.
"""
from __future__ import annotations

import csv
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import clickhouse_connect
import dlt
import pyarrow as pa
from dagster import AssetKey, MaterializeResult, MetadataValue, asset

from .settings import OrchestrationSettings, get_settings

# The seed CSV that stands in for an uploaded source dataset in the dev stack.
SEED_PATH = Path(__file__).resolve().parents[1] / "seeds" / "regional_sales.csv"

# This asset key MUST equal the key dagster-dbt assigns the `phase1.regional_sales`
# dbt source (``[source_name, table_name]``), so the dbt staging model depends on it.
RAW_ASSET_KEY = AssetKey(["phase1", "regional_sales"])


@dlt.resource(name="regional_sales", write_disposition="replace")
def regional_sales_records(seed_path: Path) -> Iterator[dict[str, Any]]:
    """dlt resource: the declarative extraction layer over the source CSV.

    Yields raw rows (no business cleaning — that is the staging model's job),
    typing the measure so the downstream Arrow schema is stable.
    """
    with seed_path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            yield {"region": row["region"], "amount": float(row["amount"])}


def _arrow_table(records: list[dict[str, Any]]) -> pa.Table:
    """Build a typed Arrow table matching the ClickHouse source columns."""
    schema = pa.schema([("region", pa.string()), ("amount", pa.float64())])
    return pa.Table.from_pylist(records, schema=schema)


def _load_to_clickhouse(
    table: pa.Table, *, settings: OrchestrationSettings
) -> str:
    """Overwrite the tenant's raw table with ``table`` over the HTTP interface.

    Idempotent (golden rule: re-runnable): the table is (re)created and truncated
    before insert, so a second run reproduces the same state — no duplicate rows.
    Returns the fully-qualified ``database.table`` identifier.
    """
    ch = settings.clickhouse
    database = settings.dbt_schema
    raw_table = settings.raw_table
    fq = f"`{database}`.`{raw_table}`"

    client = clickhouse_connect.get_client(
        host=ch.host,
        port=ch.port,
        username=ch.user,
        password=ch.password.get_secret_value(),
    )
    try:
        client.command(f"CREATE DATABASE IF NOT EXISTS `{database}`")
        client.command(
            f"CREATE TABLE IF NOT EXISTS {fq} "
            "(region String, amount Float64) ENGINE = MergeTree ORDER BY region"
        )
        client.command(f"TRUNCATE TABLE {fq}")
        client.insert_arrow(f"{database}.{raw_table}", table)
    finally:
        client.close()
    return f"{database}.{raw_table}"


@asset(
    key=RAW_ASSET_KEY,
    group_name="ingestion",
    compute_kind="dlt",
    description=(
        "Raw regional-sales source ingested via dlt into the tenant's ClickHouse "
        "database. Upstream of the dbt staging -> intermediate -> mart models."
    ),
)
def regional_sales_raw() -> MaterializeResult:
    """Materialize the raw source table the dbt `phase1` source reads."""
    settings = get_settings()
    records = list(regional_sales_records(SEED_PATH))
    table = _arrow_table(records)
    fq_table = _load_to_clickhouse(table, settings=settings)
    return MaterializeResult(
        metadata={
            "rows_loaded": MetadataValue.int(len(records)),
            "destination_table": MetadataValue.text(fq_table),
            "dlt_resource": MetadataValue.text("regional_sales"),
            "source_seed": MetadataValue.path(str(SEED_PATH)),
        }
    )
