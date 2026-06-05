"""Tests for the ClickHouse dataset registration + read-only query service (Task 1.3).

Strategy:

A live ClickHouse cluster and Iceberg REST catalog are NOT available in the test
environment (same approach as ``test_ingestion.py``). We substitute:
- ``_FakeClickHouse`` — records every ``command``/``query`` so we can assert on the
  DDL/SQL issued and the database each was bound to.
- ``_FakeCatalog`` — stands in for the Iceberg catalog and returns a fixed table
  ``location()`` so we can verify the engine URL is derived from it + settings.

Coverage:
  (a) registration creates the tenant database + an IcebergS3-engine table, both
      idempotent (``IF NOT EXISTS``) and inside the tenant's own ClickHouse db.
  (b) the engine URL and credentials come from settings (no literals).
  (c) the S3 URL is derived from the Iceberg catalog location.
  (d) read-only queries are bound to the tenant db with ``read_only=True``.
  (e) fetch_sample selects from the tenant-scoped table with the configured limit.
  (f) ISOLATION — cross-tenant dataset is rejected; queries only ever target the
      caller's own ClickHouse database.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

import pytest

from app.core.clickhouse import QueryResult
from app.core.config import Settings
from app.ingestion.csv_iceberg import _table_name_for_dataset
from app.schemas.query import Filter, Metric, QueryRequest
from app.services.clickhouse_datasets import ClickHouseDatasetService
from app.tenancy.context import TenantContext
from app.tenancy.resources import resources_for_slug

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_TENANT_ALPHA = "alpha"
_TENANT_BETA = "betacorp"

# Where the fake Iceberg catalog reports the table lives.
_ICEBERG_LOCATION = "s3://test-bucket/warehouse/alpha/dataset_x"


# ---------------------------------------------------------------------------
# Fakes & fixtures
# ---------------------------------------------------------------------------


@dataclass
class _FakeClickHouse:
    """In-memory ClickHouseClient recording every statement and its bound database."""

    rows: list[tuple[Any, ...]] = field(default_factory=list)
    column_names: list[str] = field(default_factory=list)
    commands: list[tuple[str, str | None]] = field(default_factory=list)
    queries: list[dict[str, Any]] = field(default_factory=list)

    def command(self, sql: str, *, database: str | None = None) -> None:
        self.commands.append((sql, database))

    def query(
        self,
        sql: str,
        *,
        database: str,
        parameters: Any = None,
        read_only: bool = True,
    ) -> QueryResult:
        self.queries.append(
            {
                "sql": sql,
                "database": database,
                "read_only": read_only,
                "parameters": dict(parameters) if parameters else {},
            }
        )
        return QueryResult(column_names=list(self.column_names), rows=list(self.rows))


@dataclass
class _FakeIcebergTable:
    loc: str

    def location(self) -> str:
        return self.loc


@dataclass
class _FakeCatalog:
    loc: str
    loaded: list[tuple[str, str]] = field(default_factory=list)

    def load_table(self, identifier: tuple[str, str]) -> _FakeIcebergTable:
        self.loaded.append(identifier)
        return _FakeIcebergTable(self.loc)


@dataclass
class _FakeDataset:
    """Minimal Dataset stand-in for testing."""

    id: uuid.UUID
    tenant_id: uuid.UUID


def _make_ctx(slug: str) -> TenantContext:
    res = resources_for_slug(slug)
    return TenantContext(
        tenant_id=str(uuid.uuid4()),
        iceberg_namespace=res.iceberg_namespace,
        clickhouse_db=res.clickhouse_db,
        dbt_schema=res.dbt_schema,
    )


def _make_settings() -> Settings:
    """Build a Settings instance with fake-but-valid env values for testing."""
    import os

    env: dict[str, str] = {
        "ENVIRONMENT": "test",
        "POSTGRES__HOST": "localhost",
        "POSTGRES__USER": "test",
        "POSTGRES__PASSWORD": "test",
        "POSTGRES__DB": "test",
        "REDIS__HOST": "localhost",
        "OBJECT_STORE__ENDPOINT_URL": "http://localhost:9000",
        "OBJECT_STORE__ACCESS_KEY": "testkey",
        "OBJECT_STORE__SECRET_KEY": "testsecret",
        "OBJECT_STORE__BUCKET": "test-bucket",
        "ICEBERG__CATALOG_URI": "http://localhost:8181",
        "ICEBERG__WAREHOUSE": "s3://test-bucket/warehouse",
        "CLICKHOUSE__HOST": "localhost",
        "CLICKHOUSE__PASSWORD": "test",
        "AI__PROVIDER": "openai",
        "AI__MODEL": "gpt-4o",
        "AI__API_KEY": "test",
        "AI__PROMPT_TEMPLATE_DIR": "prompts",
        "CUBE__BASE_URL": "http://cube:4000",
        "CUBE__API_SECRET": "test-cube-secret-at-least-32-chars!",
        "AUTH__DEV_STUB": "true",
        "AUTH__DEV_STUB_SECRET": "test-secret-at-least-32-chars-long!",
        "AUTH__TENANT_CLAIM": "tenant",
        "SEED_TENANT__SLUG": "local",
        "SEED_TENANT__NAME": "Local",
        "SEED_TENANT__ADMIN_EMAIL": "admin@local.test",
    }

    original = {}
    for k, v in env.items():
        original[k] = os.environ.get(k)
        os.environ[k] = v

    from app.core.config import get_settings

    get_settings.cache_clear()
    settings = Settings()

    for k, v in original.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    get_settings.cache_clear()

    return settings


@pytest.fixture
def fake_catalog() -> Iterator[_FakeCatalog]:
    """Patch ``load_iceberg_catalog`` (active for the whole test) to return a fake.

    Requested only by tests that exercise registration; the patch is torn down at
    test end so it never leaks into other tests.
    """
    cat = _FakeCatalog(loc=_ICEBERG_LOCATION)
    with patch(
        "app.services.clickhouse_datasets.load_iceberg_catalog", return_value=cat
    ):
        yield cat


# ---------------------------------------------------------------------------
# (a) Registration creates db + Iceberg-engine table, idempotently, in tenant db
# ---------------------------------------------------------------------------


def test_register_creates_database_and_table_in_tenant_db(
    fake_catalog: _FakeCatalog,
) -> None:
    ctx = _make_ctx(_TENANT_ALPHA)
    settings = _make_settings()
    ch = _FakeClickHouse()
    service = ClickHouseDatasetService(ch=ch, settings=settings)

    dataset = _FakeDataset(id=uuid.uuid4(), tenant_id=uuid.UUID(ctx.tenant_id))
    table_name = _table_name_for_dataset(dataset.id)

    qualified = service.register_dataset(ctx, dataset)  # type: ignore[arg-type]

    assert qualified == f"{ctx.clickhouse_db}.{table_name}"

    # Two DDL statements: CREATE DATABASE then CREATE TABLE.
    assert len(ch.commands) == 2
    create_db_sql, create_db_db = ch.commands[0]
    create_tbl_sql, create_tbl_db = ch.commands[1]

    # CREATE DATABASE targets the tenant db, is idempotent, runs without a bound db.
    assert "CREATE DATABASE IF NOT EXISTS" in create_db_sql
    assert ctx.clickhouse_db in create_db_sql
    assert create_db_db is None

    # CREATE TABLE is idempotent, fully qualified to the tenant db, Iceberg-engine.
    assert "CREATE TABLE IF NOT EXISTS" in create_tbl_sql
    assert f"`{ctx.clickhouse_db}`.`{table_name}`" in create_tbl_sql
    assert "ENGINE = IcebergS3(" in create_tbl_sql
    assert create_tbl_db is None


# ---------------------------------------------------------------------------
# (b) + (c) Engine URL/credentials come from settings + Iceberg catalog location
# ---------------------------------------------------------------------------


def test_register_engine_url_and_credentials_from_settings(
    fake_catalog: _FakeCatalog,
) -> None:
    ctx = _make_ctx(_TENANT_ALPHA)
    settings = _make_settings()
    ch = _FakeClickHouse()
    service = ClickHouseDatasetService(ch=ch, settings=settings)

    dataset = _FakeDataset(id=uuid.uuid4(), tenant_id=uuid.UUID(ctx.tenant_id))
    service.register_dataset(ctx, dataset)  # type: ignore[arg-type]

    create_tbl_sql = ch.commands[1][0]

    # URL = endpoint + location-without-scheme (derived from the catalog location).
    expected_url = "http://localhost:9000/test-bucket/warehouse/alpha/dataset_x"
    assert f"'{expected_url}'" in create_tbl_sql

    # Credentials come from object-store settings, not literals in the service.
    assert f"'{settings.object_store.access_key.get_secret_value()}'" in create_tbl_sql
    assert f"'{settings.object_store.secret_key.get_secret_value()}'" in create_tbl_sql

    # The catalog was consulted for the table's real location (tenant namespace).
    table_name = _table_name_for_dataset(dataset.id)
    assert fake_catalog.loaded == [(ctx.iceberg_namespace, table_name)]


def test_s3_url_conversion_handles_schemes() -> None:
    settings = _make_settings()
    service = ClickHouseDatasetService(ch=_FakeClickHouse(), settings=settings)

    base = "http://localhost:9000/test-bucket/warehouse/t/d"
    assert service._to_clickhouse_s3_url("s3://test-bucket/warehouse/t/d") == base
    assert service._to_clickhouse_s3_url("s3a://test-bucket/warehouse/t/d") == base


# ---------------------------------------------------------------------------
# (d) + (e) Read-only, tenant-scoped queries
# ---------------------------------------------------------------------------


def test_run_read_only_query_is_scoped_and_readonly() -> None:
    ctx = _make_ctx(_TENANT_ALPHA)
    settings = _make_settings()
    ch = _FakeClickHouse(column_names=["n"], rows=[(1,)])
    service = ClickHouseDatasetService(ch=ch, settings=settings)

    result = service.run_read_only_query(ctx, "SELECT 1 AS n")

    assert result.rows == [(1,)]
    assert len(ch.queries) == 1
    assert ch.queries[0]["database"] == ctx.clickhouse_db
    assert ch.queries[0]["read_only"] is True


def test_fetch_sample_selects_from_tenant_table() -> None:
    ctx = _make_ctx(_TENANT_ALPHA)
    settings = _make_settings()
    ch = _FakeClickHouse(column_names=["id", "name"], rows=[(1, "a"), (2, "b")])
    service = ClickHouseDatasetService(ch=ch, settings=settings)

    dataset = _FakeDataset(id=uuid.uuid4(), tenant_id=uuid.UUID(ctx.tenant_id))
    table_name = _table_name_for_dataset(dataset.id)

    result = service.fetch_sample(ctx, dataset)  # type: ignore[arg-type]

    # Acceptance: a SELECT against the dataset returns rows.
    assert result.rows == [(1, "a"), (2, "b")]
    assert result.as_dicts() == [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]

    query = ch.queries[0]
    assert query["database"] == ctx.clickhouse_db
    assert query["read_only"] is True
    assert f"`{ctx.clickhouse_db}`.`{table_name}`" in query["sql"]
    # Limit comes from settings, not a literal.
    assert f"LIMIT {settings.default_page_size}" in query["sql"]


def test_fetch_sample_respects_explicit_limit() -> None:
    ctx = _make_ctx(_TENANT_ALPHA)
    settings = _make_settings()
    ch = _FakeClickHouse()
    service = ClickHouseDatasetService(ch=ch, settings=settings)

    dataset = _FakeDataset(id=uuid.uuid4(), tenant_id=uuid.UUID(ctx.tenant_id))
    service.fetch_sample(ctx, dataset, limit=7)  # type: ignore[arg-type]

    assert "LIMIT 7" in ch.queries[0]["sql"]


# ---------------------------------------------------------------------------
# (g) Aggregation builder (Task 1.4) — safe, parameterised, row-capped
# ---------------------------------------------------------------------------


def test_run_aggregation_builds_grouped_parameterised_sql() -> None:
    ctx = _make_ctx(_TENANT_ALPHA)
    settings = _make_settings()
    ch = _FakeClickHouse(column_names=["region", "total"], rows=[("eu", 10)])
    service = ClickHouseDatasetService(ch=ch, settings=settings)

    dataset = _FakeDataset(id=uuid.uuid4(), tenant_id=uuid.UUID(ctx.tenant_id))
    table_name = _table_name_for_dataset(dataset.id)
    request = QueryRequest(
        dimensions=["region"],
        metrics=[Metric(function="sum", column="amount", alias="total")],
        filters=[Filter(column="region", op="=", value="eu")],
    )

    result = service.run_aggregation(ctx, dataset, request)  # type: ignore[arg-type]

    # Acceptance: aggregated rows come back.
    assert result.rows == [("eu", 10)]

    query = ch.queries[0]
    sql = query["sql"]
    # Bound to the tenant db, read-only.
    assert query["database"] == ctx.clickhouse_db
    assert query["read_only"] is True
    # Identifiers are backtick-quoted; the table is the tenant-scoped dataset table.
    assert "`region`" in sql
    assert "sum(`amount`) AS `total`" in sql
    assert f"`{ctx.clickhouse_db}`.`{table_name}`" in sql
    assert "GROUP BY `region`" in sql
    # The filter value is bound as a parameter, never interpolated.
    assert "`region` = {p0:String}" in sql
    assert query["parameters"] == {"p0": "eu"}
    assert "'eu'" not in sql
    # Row cap comes from settings, not a literal.
    assert f"LIMIT {settings.max_query_rows}" in sql


def test_run_aggregation_count_star_without_column() -> None:
    ctx = _make_ctx(_TENANT_ALPHA)
    service = ClickHouseDatasetService(ch=_FakeClickHouse(), settings=_make_settings())
    dataset = _FakeDataset(id=uuid.uuid4(), tenant_id=uuid.UUID(ctx.tenant_id))

    request = QueryRequest(metrics=[Metric(function="count", alias="n")])
    service.run_aggregation(ctx, dataset, request)  # type: ignore[arg-type]

    sql = service._ch.queries[0]["sql"]  # type: ignore[attr-defined]
    assert "count(*) AS `n`" in sql
    # No dimensions → a single global aggregate, no GROUP BY.
    assert "GROUP BY" not in sql


def test_run_aggregation_clamps_limit_to_settings() -> None:
    ctx = _make_ctx(_TENANT_ALPHA)
    settings = _make_settings()
    service = ClickHouseDatasetService(ch=_FakeClickHouse(), settings=settings)
    dataset = _FakeDataset(id=uuid.uuid4(), tenant_id=uuid.UUID(ctx.tenant_id))

    # Over the cap is clamped down...
    over = QueryRequest(
        metrics=[Metric(function="count")], limit=settings.max_query_rows + 5_000
    )
    service.run_aggregation(ctx, dataset, over)  # type: ignore[arg-type]
    assert f"LIMIT {settings.max_query_rows}" in service._ch.queries[-1]["sql"]  # type: ignore[attr-defined]

    # ...a smaller request limit is honoured.
    under = QueryRequest(metrics=[Metric(function="count")], limit=10)
    service.run_aggregation(ctx, dataset, under)  # type: ignore[arg-type]
    assert "LIMIT 10" in service._ch.queries[-1]["sql"]  # type: ignore[attr-defined]


def test_run_aggregation_binds_value_types() -> None:
    ctx = _make_ctx(_TENANT_ALPHA)
    service = ClickHouseDatasetService(ch=_FakeClickHouse(), settings=_make_settings())
    dataset = _FakeDataset(id=uuid.uuid4(), tenant_id=uuid.UUID(ctx.tenant_id))

    request = QueryRequest(
        metrics=[Metric(function="count")],
        filters=[
            Filter(column="qty", op=">", value=5),
            Filter(column="active", op="=", value=True),
            Filter(column="price", op="<", value=9.5),
            Filter(column="name", op="=", value="x"),
        ],
    )
    service.run_aggregation(ctx, dataset, request)  # type: ignore[arg-type]

    query = service._ch.queries[0]  # type: ignore[attr-defined]
    sql = query["sql"]
    # bool is checked before int (bool is an int subclass).
    assert "{p0:Int64}" in sql
    assert "{p1:Bool}" in sql
    assert "{p2:Float64}" in sql
    assert "{p3:String}" in sql
    assert query["parameters"] == {"p0": 5, "p1": True, "p2": 9.5, "p3": "x"}


def test_isolation_run_aggregation_cross_tenant_rejected() -> None:
    ctx_a = _make_ctx(_TENANT_ALPHA)
    ctx_b = _make_ctx(_TENANT_BETA)
    ch = _FakeClickHouse()
    service = ClickHouseDatasetService(ch=ch, settings=_make_settings())

    dataset_b = _FakeDataset(id=uuid.uuid4(), tenant_id=uuid.UUID(ctx_b.tenant_id))
    request = QueryRequest(metrics=[Metric(function="count")])

    with pytest.raises(ValueError, match=str(dataset_b.tenant_id)):
        service.run_aggregation(ctx_a, dataset_b, request)  # type: ignore[arg-type]

    # Fail closed: nothing reached ClickHouse.
    assert ch.queries == []


# ---------------------------------------------------------------------------
# (f) ISOLATION
# ---------------------------------------------------------------------------


def test_isolation_register_cross_tenant_rejected() -> None:
    ctx_a = _make_ctx(_TENANT_ALPHA)
    ctx_b = _make_ctx(_TENANT_BETA)
    settings = _make_settings()
    ch = _FakeClickHouse()
    service = ClickHouseDatasetService(ch=ch, settings=settings)

    # Dataset belongs to tenant B; registering it through tenant A's context fails.
    dataset_b = _FakeDataset(id=uuid.uuid4(), tenant_id=uuid.UUID(ctx_b.tenant_id))

    with pytest.raises(ValueError, match=str(dataset_b.tenant_id)):
        service.register_dataset(ctx_a, dataset_b)  # type: ignore[arg-type]

    # Nothing was issued to ClickHouse — fail closed before any DDL.
    assert ch.commands == []


def test_isolation_fetch_sample_cross_tenant_rejected() -> None:
    ctx_a = _make_ctx(_TENANT_ALPHA)
    ctx_b = _make_ctx(_TENANT_BETA)
    settings = _make_settings()
    ch = _FakeClickHouse()
    service = ClickHouseDatasetService(ch=ch, settings=settings)

    dataset_b = _FakeDataset(id=uuid.uuid4(), tenant_id=uuid.UUID(ctx_b.tenant_id))

    with pytest.raises(ValueError, match=str(dataset_b.tenant_id)):
        service.fetch_sample(ctx_a, dataset_b)  # type: ignore[arg-type]

    assert ch.queries == []


def test_isolation_queries_target_only_own_database() -> None:
    ctx_a = _make_ctx(_TENANT_ALPHA)
    ctx_b = _make_ctx(_TENANT_BETA)
    settings = _make_settings()
    ch = _FakeClickHouse()
    service = ClickHouseDatasetService(ch=ch, settings=settings)

    service.run_read_only_query(ctx_a, "SELECT 1")
    service.run_read_only_query(ctx_b, "SELECT 1")

    dbs = [q["database"] for q in ch.queries]
    assert dbs == [ctx_a.clickhouse_db, ctx_b.clickhouse_db]
    # Distinct tenant databases — no cross-tenant bleed.
    assert ctx_a.clickhouse_db != ctx_b.clickhouse_db
