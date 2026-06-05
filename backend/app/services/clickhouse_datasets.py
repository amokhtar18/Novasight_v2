"""Make a tenant's Iceberg dataset queryable through its ClickHouse database (Task 1.3).

Two responsibilities, both strictly tenant-scoped:

* ``register_dataset`` — ensure the tenant's ClickHouse database exists and create a
  table in it, backed by the **Iceberg table engine**, that points at the dataset's
  Iceberg table in object storage. Idempotent (``IF NOT EXISTS``).
* ``run_read_only_query`` / ``fetch_sample`` — execute a read-only query bound to the
  tenant's ClickHouse database.

## Tenant isolation (the invariant)

The ClickHouse database name is taken verbatim from ``TenantContext.clickhouse_db``,
which is resolved server-side from the authenticated JWT — never a caller parameter.
``register_dataset`` and ``fetch_sample`` additionally assert that the dataset belongs
to the context tenant before touching anything. Reads go through
``ClickHouseClient.query`` which binds the connection to the tenant database, so an
unqualified table reference can only resolve inside that database.

## Why the Iceberg table engine (vs a load/copy step)

ClickHouse's ``IcebergS3`` engine reads the Iceberg table in place from object
storage, so there is no second copy of the data to keep in sync and no extra load
job — the serving layer queries the same files the lake already holds. The physical
location is resolved from the Iceberg **catalog** (the source of truth for where the
table lives), not hand-computed, so it stays correct regardless of the catalog's
internal layout.

## Configuration

All infra-pointing values come from ``Settings``: ClickHouse connection from
``settings.clickhouse`` (via the injected client), the object-store endpoint and S3
credentials the engine needs from ``settings.object_store``. No literal hosts, URIs,
buckets, or credentials appear here (golden rule 1).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastapi import Depends

from app.core.clickhouse import ClickHouseClient, QueryResult, get_clickhouse_client
from app.core.config import Settings, get_settings
from app.core.iceberg_catalog import load_iceberg_catalog
from app.ingestion.csv_iceberg import _table_name_for_dataset
from app.schemas.query import Filter, Metric, QueryRequest
from app.tenancy.context import TenantContext

if TYPE_CHECKING:
    from app.models.dataset import Dataset

logger = logging.getLogger(__name__)


def _ident(name: str) -> str:
    """Backtick-quote a ClickHouse identifier (database/table name).

    Names are derived from a validated tenant slug and a UUID hex, so they are
    already safe; quoting is defensive against reserved words.
    """
    return f"`{name}`"


def _str_literal(value: str) -> str:
    """Single-quote and escape a ClickHouse string literal."""
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def _clickhouse_param_type(value: object) -> str:
    """Map a Python filter value to the ClickHouse type for its bound parameter.

    ``bool`` is checked before ``int`` because ``bool`` is an ``int`` subclass.
    """
    if isinstance(value, bool):
        return "Bool"
    if isinstance(value, int):
        return "Int64"
    if isinstance(value, float):
        return "Float64"
    return "String"


class ClickHouseDatasetService:
    """Register Iceberg datasets in, and run read-only queries against, one tenant's DB.

    Constructor accepts only infrastructure dependencies (ClickHouse client,
    settings). The tenant scope is supplied per call as a server-resolved
    ``TenantContext`` — never a database name from an untrusted caller.
    """

    def __init__(self, ch: ClickHouseClient, settings: Settings) -> None:
        self._ch = ch
        self._settings = settings

    # ------------------------------------------------------------------
    # Registration (Iceberg table engine)
    # ------------------------------------------------------------------

    def register_dataset(self, ctx: TenantContext, dataset: Dataset) -> str:
        """Make ``dataset``'s Iceberg table queryable from the tenant's ClickHouse DB.

        Creates the tenant database if needed, then creates an ``IcebergS3``-engine
        table pointing at the dataset's Iceberg table location. Idempotent.

        Returns:
            The fully-qualified ClickHouse table identifier ``<db>.<table>``.

        Raises:
            ValueError: if the dataset does not belong to this tenant context.
        """
        self._assert_dataset_belongs_to_tenant(ctx, dataset)

        table_name = _table_name_for_dataset(dataset.id)
        s3_url = self._iceberg_s3_url(ctx, table_name)

        db = ctx.clickhouse_db
        logger.info(
            "Registering dataset %s in ClickHouse db=%r table=%r",
            dataset.id,
            db,
            table_name,
        )

        # Create the tenant database first (no database bound — it may not exist yet).
        self._ch.command(f"CREATE DATABASE IF NOT EXISTS {_ident(db)}")

        # Create the Iceberg-engine table inside the tenant database. Fully
        # qualified so it always lands in the tenant's own database.
        os_cfg = self._settings.object_store
        engine = (
            "IcebergS3("
            f"{_str_literal(s3_url)}, "
            f"{_str_literal(os_cfg.access_key.get_secret_value())}, "
            f"{_str_literal(os_cfg.secret_key.get_secret_value())})"
        )
        self._ch.command(
            f"CREATE TABLE IF NOT EXISTS {_ident(db)}.{_ident(table_name)} "
            f"ENGINE = {engine}"
        )

        qualified = f"{db}.{table_name}"
        logger.info("Dataset %s registered as ClickHouse table %s", dataset.id, qualified)
        return qualified

    # ------------------------------------------------------------------
    # Read-only, tenant-scoped queries
    # ------------------------------------------------------------------

    def run_read_only_query(
        self,
        ctx: TenantContext,
        sql: str,
        *,
        parameters: dict[str, Any] | None = None,
    ) -> QueryResult:
        """Run ``sql`` read-only, bound to the tenant's ClickHouse database.

        The connection is opened against ``ctx.clickhouse_db`` and ClickHouse's
        ``readonly`` setting is enforced, so the query can neither mutate data nor
        resolve unqualified tables outside the tenant database. ``parameters`` are
        passed through to ClickHouse's server-side parameter binding so caller values
        are never interpolated into the SQL text.
        """
        return self._ch.query(
            sql,
            database=ctx.clickhouse_db,
            parameters=parameters,
            read_only=True,
        )

    def fetch_sample(
        self, ctx: TenantContext, dataset: Dataset, *, limit: int | None = None
    ) -> QueryResult:
        """Return up to ``limit`` rows from ``dataset`` through the tenant's DB.

        Demonstrates the Task 1.3 acceptance: a ``SELECT`` against the dataset
        returns rows through the tenant's ClickHouse database only. ``limit``
        defaults to the configured ``default_page_size`` (never a literal).
        """
        self._assert_dataset_belongs_to_tenant(ctx, dataset)
        effective_limit = self._settings.default_page_size if limit is None else limit

        table_name = _table_name_for_dataset(dataset.id)
        # Not user input: db = validated tenant slug, table = UUID hex, limit coerced
        # to int — nothing interpolated is client-controlled, and it runs read-only.
        db_ident = _ident(ctx.clickhouse_db)
        tbl_ident = _ident(table_name)
        sql = f"SELECT * FROM {db_ident}.{tbl_ident} LIMIT {int(effective_limit)}"  # noqa: S608
        return self.run_read_only_query(ctx, sql)

    def run_aggregation(
        self, ctx: TenantContext, dataset: Dataset, request: QueryRequest
    ) -> QueryResult:
        """Compile ``request`` into a read-only aggregation and run it tenant-scoped.

        Identifiers in ``request`` are already pattern-constrained by the schema and
        are backtick-quoted here; filter values are bound as ClickHouse parameters; the
        row cap is clamped to ``settings.max_query_rows``. The result therefore cannot
        mutate data, reference another tenant's table, or carry injected SQL.
        """
        self._assert_dataset_belongs_to_tenant(ctx, dataset)
        table_name = _table_name_for_dataset(dataset.id)
        sql, parameters = self._build_aggregation_sql(ctx, table_name, request)
        return self.run_read_only_query(ctx, sql, parameters=parameters)

    def _build_aggregation_sql(
        self, ctx: TenantContext, table_name: str, request: QueryRequest
    ) -> tuple[str, dict[str, Any]]:
        """Build the ``SELECT`` text + bound parameters for an aggregation request."""
        select_parts: list[str] = [_ident(dim) for dim in request.dimensions]
        for index, metric in enumerate(request.metrics):
            select_parts.append(self._metric_expr(metric, index))

        db_ident = _ident(ctx.clickhouse_db)
        tbl_ident = _ident(table_name)
        sql = f"SELECT {', '.join(select_parts)} FROM {db_ident}.{tbl_ident}"  # noqa: S608

        where_sql, parameters = self._where_clause(request.filters)
        if where_sql:
            sql += f" WHERE {where_sql}"

        if request.dimensions:
            group_idents = ", ".join(_ident(dim) for dim in request.dimensions)
            sql += f" GROUP BY {group_idents}"

        # Clamp the requested row cap to the platform maximum (never a literal limit).
        cap = self._settings.max_query_rows
        limit = cap if request.limit is None else min(request.limit, cap)
        sql += f" LIMIT {int(limit)}"
        return sql, parameters

    @staticmethod
    def _metric_expr(metric: Metric, index: int) -> str:
        """Render one metric as ``fn(col) AS alias`` (or ``count(*) AS alias``)."""
        if metric.column is None:
            # Only ``count`` may omit a column (the schema validator enforces this),
            # in which case it counts every row.
            expr = f"{metric.function}(*)"
        else:
            expr = f"{metric.function}({_ident(metric.column)})"
        alias = metric.alias or f"{metric.function}_{index}"
        return f"{expr} AS {_ident(alias)}"

    @staticmethod
    def _where_clause(filters: list[Filter]) -> tuple[str, dict[str, Any]]:
        """Build a parameterised WHERE clause; values are bound, never interpolated."""
        clauses: list[str] = []
        parameters: dict[str, Any] = {}
        for index, flt in enumerate(filters):
            name = f"p{index}"
            ch_type = _clickhouse_param_type(flt.value)
            clauses.append(f"{_ident(flt.column)} {flt.op} {{{name}:{ch_type}}}")
            parameters[name] = flt.value
        return " AND ".join(clauses), parameters

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _assert_dataset_belongs_to_tenant(ctx: TenantContext, dataset: Dataset) -> None:
        if str(dataset.tenant_id) != ctx.tenant_id:
            raise ValueError(
                f"Dataset {dataset.id} belongs to tenant {dataset.tenant_id!r}, "
                f"not {ctx.tenant_id!r}"
            )

    def _iceberg_s3_url(self, ctx: TenantContext, table_name: str) -> str:
        """Resolve the dataset's Iceberg table location and convert it to an S3 URL.

        The location comes from the Iceberg catalog (source of truth), not a
        hand-built path, then is rewritten to the ClickHouse-style endpoint URL
        using the configured object-store endpoint.
        """
        catalog = load_iceberg_catalog(self._settings, name=ctx.iceberg_namespace)
        iceberg_table = catalog.load_table((ctx.iceberg_namespace, table_name))
        location: str = iceberg_table.location()
        return self._to_clickhouse_s3_url(location)

    def _to_clickhouse_s3_url(self, location: str) -> str:
        """Rewrite an ``s3://bucket/key`` location to a ClickHouse ``IcebergS3`` URL.

        ClickHouse's S3 functions take an endpoint-style URL (``<endpoint>/<bucket>/
        <key>``). When the object store has an explicit endpoint (MinIO and most
        S3-compatible services) we build that form; for native AWS S3 (no endpoint)
        we pass the location through unchanged.
        """
        endpoint = self._settings.object_store.endpoint_url
        path = location
        for scheme in ("s3://", "s3a://"):
            if path.startswith(scheme):
                path = path[len(scheme) :]
                break
        if endpoint:
            return f"{endpoint.rstrip('/')}/{path}"
        return location


def get_clickhouse_dataset_service(
    ch: ClickHouseClient = Depends(get_clickhouse_client),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> ClickHouseDatasetService:
    """FastAPI dependency: assemble a ``ClickHouseDatasetService`` from request scope."""
    return ClickHouseDatasetService(ch=ch, settings=settings)
