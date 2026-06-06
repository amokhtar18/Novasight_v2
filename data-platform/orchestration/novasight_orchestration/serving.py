"""Load the validated mart into the tenant's ClickHouse serving table (asset).

This is step 4 of the standard pipeline shape (dbt-dagster-workflow skill): *"Mart
loaded into the tenant's ClickHouse database for serving (asset)"* — the final hop
before the serving / semantic / AI layers read the data.

## Why a distinct serving asset (and not "dbt already wrote ClickHouse")

In the canonical architecture (``docs/ARCHITECTURE.md``) dbt builds marts in the
Iceberg lakehouse and a downstream step **hydrates** the tenant's ClickHouse database
from the *validated* mart. The dev/on-prem compose stack takes a shortcut — dbt's
``clickhouse`` target builds ``mart_regional_sales`` directly inside the tenant DB (the
stack exposes only ClickHouse over HTTP; see ``ingestion.py``). This asset preserves the
real seam regardless: it promotes the dbt-built mart into a **stable, config-named
serving table** that the serving layer reads, decoupled from dbt's internal model name.

The promotion only runs for a *validated* mart: this asset is wired **downstream of the
dbt mart asset** (``deps``), and the mart asset only materializes when the upstream dbt
quality gate (asset checks in ``dbt_assets.py``) passed. So "quality gate before
serving" (dbt-dagster-workflow skill) holds — an unvalidated mart never reaches the
serving table.

## Integrity check

After the load, a post-load **asset check** (``serving_matches_mart``) verifies the
serving table is non-empty and row-for-row consistent with the source mart, catching a
partial or empty copy before anything queries it.

## Configuration & tenancy

Every value comes from ``OrchestrationSettings`` (golden rule 1): no host, port,
credential, database, or table name is hardcoded. The load is scoped to the tenant's
ClickHouse database (``settings.dbt_schema``), resolved at the boundary — golden rule 2.
"""
from __future__ import annotations

from typing import Any, Protocol

import clickhouse_connect
from dagster import (
    AssetCheckResult,
    AssetCheckSeverity,
    AssetCheckSpec,
    AssetKey,
    MaterializeResult,
    MetadataValue,
    asset,
)

from .settings import OrchestrationSettings, get_settings

# Asset key dagster-dbt assigns the dbt mart model (``[model_name]``). Depending on it
# makes this asset downstream of the blocking quality gate, so only a validated mart is
# ever served.
MART_ASSET_KEY = AssetKey(["mart_regional_sales"])

# Physical ClickHouse table name of the dbt mart. This is the dbt **model name**, which
# is identical across every environment and tenant (tenancy varies the *database*, not
# the model name — golden rule 1), so it is a code-level constant, not configuration.
MART_TABLE = "mart_regional_sales"

# This asset's key and the name of its integrity check.
SERVING_ASSET_KEY = AssetKey(["mart_regional_sales_serving"])
SERVING_CHECK_NAME = "serving_matches_mart"


class ClickHouseClient(Protocol):
    """The slice of a ClickHouse client this module needs (``clickhouse_connect``).

    Declared as a Protocol so the load logic is unit-testable with a fake client — no
    live warehouse required, matching the gate-stream tests.
    """

    def command(self, cmd: str, *args: Any, **kwargs: Any) -> Any: ...

    def close(self) -> None: ...


def _connect(settings: OrchestrationSettings) -> ClickHouseClient:
    """Open a ClickHouse client from settings (same HTTP seam the ingestion uses)."""
    ch = settings.clickhouse
    return clickhouse_connect.get_client(
        host=ch.host,
        port=ch.port,
        username=ch.user,
        password=ch.password.get_secret_value(),
    )


def _count(client: ClickHouseClient, fq_table: str) -> int:
    """Return the row count of a fully-qualified table."""
    return int(client.command(f"SELECT count() FROM {fq_table}"))


def promote_mart(
    client: ClickHouseClient,
    *,
    database: str,
    mart_table: str,
    serving_table: str,
) -> tuple[int, int]:
    """Publish the validated mart into the tenant's serving table; return row counts.

    Idempotent (golden rule: re-runnable): ``CREATE OR REPLACE TABLE`` atomically swaps
    the serving table in place, so a re-run reproduces the same state with no partial
    window where the serving surface is missing or half-built. Every identifier is
    qualified with ``database`` — the tenant's ClickHouse DB resolved at the boundary —
    so the load is tenant-scoped (golden rule 2) and never touches another tenant's data.

    Returns ``(serving_rows, mart_rows)`` for the post-load integrity check.
    """
    mart_fq = f"`{database}`.`{mart_table}`"
    serving_fq = f"`{database}`.`{serving_table}`"

    client.command(f"CREATE DATABASE IF NOT EXISTS `{database}`")
    # Server-side copy of the already-validated mart into the stable serving table.
    # ORDER BY region matches the mart's grain (one row per region) for serving reads.
    client.command(
        f"CREATE OR REPLACE TABLE {serving_fq} "
        f"ENGINE = MergeTree ORDER BY region AS SELECT * FROM {mart_fq}"
    )
    return _count(client, serving_fq), _count(client, mart_fq)


def build_serving_check(*, serving_rows: int, mart_rows: int) -> AssetCheckResult:
    """Post-load integrity check: the serving table mirrors the validated mart.

    Pure (no I/O) so good- and bad-data cases are asserted directly in tests. Fails when
    the serving table is empty or its row count diverges from the source mart — i.e. a
    partial or empty load reached the serving surface.
    """
    passed = serving_rows > 0 and serving_rows == mart_rows
    return AssetCheckResult(
        passed=passed,
        check_name=SERVING_CHECK_NAME,
        severity=AssetCheckSeverity.ERROR,
        metadata={
            "serving_rows": serving_rows,
            "mart_rows": mart_rows,
            "matches": passed,
        },
        description=(
            "Serving table row count matches the validated mart and is non-empty."
            if passed
            else (
                f"Serving load mismatch: {serving_rows} serving row(s) vs "
                f"{mart_rows} mart row(s). The serving table is empty or incomplete."
            )
        ),
    )


def run_serving_load(
    settings: OrchestrationSettings, *, connect: Any = _connect
) -> MaterializeResult:
    """Load the mart into the tenant serving table and attach the integrity check.

    Factored out of the asset body so the full unit (load + check + tenant-scoped
    metadata) is testable with a fake ``connect`` and no Dagster run.
    """
    client = connect(settings)
    try:
        serving_rows, mart_rows = promote_mart(
            client,
            database=settings.dbt_schema,
            mart_table=MART_TABLE,
            serving_table=settings.serving_table,
        )
    finally:
        client.close()

    serving_fq = f"{settings.dbt_schema}.{settings.serving_table}"
    return MaterializeResult(
        metadata={
            "serving_table": MetadataValue.text(serving_fq),
            "source_mart": MetadataValue.text(f"{settings.dbt_schema}.{MART_TABLE}"),
            "rows_served": MetadataValue.int(serving_rows),
        },
        check_results=[build_serving_check(serving_rows=serving_rows, mart_rows=mart_rows)],
    )


@asset(
    key=SERVING_ASSET_KEY,
    deps=[MART_ASSET_KEY],
    group_name="serving",
    compute_kind="clickhouse",
    description=(
        "Publishes the validated mart_regional_sales mart into the tenant's ClickHouse "
        "serving table. Downstream of the dbt quality gate, so only a validated mart is "
        "served. Re-runnable (CREATE OR REPLACE); tenant-scoped to the tenant database."
    ),
    check_specs=[AssetCheckSpec(name=SERVING_CHECK_NAME, asset=SERVING_ASSET_KEY)],
)
def mart_regional_sales_serving() -> MaterializeResult:
    """Materialize the tenant's serving table from the validated mart."""
    return run_serving_load(get_settings())
