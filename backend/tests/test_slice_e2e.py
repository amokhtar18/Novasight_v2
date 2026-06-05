"""End-to-end vertical-slice test: CSV upload → pipeline → ClickHouse register → query.

This module is the *chain* test that unit tests deliberately avoid: it wires the
real service objects across every seam (upload → object store → pipeline → ClickHouse
registration → query endpoint) for a single tenant and asserts that the boundary
between each stage passes the right data with the right tenant scope.

Coverage:
  (1) upload: POST /datasets/upload stores the CSV under the tenant's namespace prefix.
  (2) pipeline: CsvIcebergPipeline reads the exact bytes upload stored and returns the
      expected Iceberg table identifier.
  (3) register: ClickHouseDatasetService issues tenant-scoped CREATE DATABASE + CREATE
      TABLE DDL with the correct db, and returns a qualified table name.
  (4) query: POST /datasets/{id}/query runs a parameterised aggregation bound to the
      tenant's ClickHouse database, read-only.
  (5) e2e-boundary: the iceberg_namespace used by the pipeline, the object-key prefix
      stored by upload, and the clickhouse_db hit by the query are all consistent with
      the single tenant's resource map — no cross-tenant bleed.

Isolation coverage note: the three new endpoints already have direct cross-tenant
isolation assertions in test_datasets.py:
  - list   → test_tenant_cannot_list_other_tenants_datasets
  - query  → test_tenant_cannot_query_other_tenants_dataset
  - upload → prefix-partitioning asserted inside the list isolation test
No isolation tests are added here; see existing file for those.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clickhouse import QueryResult
from app.core.config import Settings
from app.ingestion.csv_iceberg import CsvIcebergPipeline, _table_name_for_dataset
from app.models.dataset import Dataset
from app.services.clickhouse_datasets import ClickHouseDatasetService
from app.tenancy import resources_for_slug
from app.tenancy.context import TenantContext

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_DEV_STUB_SECRET = "test-dev-stub-secret-do-not-use-in-production"

_FAKE_ENV: dict[str, str] = {
    "ENVIRONMENT": "test",
    "POSTGRES__HOST": "localhost",
    "POSTGRES__USER": "test",
    "POSTGRES__PASSWORD": "test",
    "POSTGRES__DB": "test",
    "REDIS__HOST": "localhost",
    "OBJECT_STORE__ENDPOINT_URL": "http://localhost:9000",
    "OBJECT_STORE__ACCESS_KEY": "test",
    "OBJECT_STORE__SECRET_KEY": "test",
    "OBJECT_STORE__BUCKET": "test",
    "ICEBERG__CATALOG_URI": "http://localhost:8181",
    "ICEBERG__WAREHOUSE": "s3://test/",
    "CLICKHOUSE__HOST": "localhost",
    "CLICKHOUSE__PASSWORD": "test",
    "AI__PROVIDER": "openai",
    "AI__MODEL": "gpt-4o",
    "AI__API_KEY": "test",
    "AI__PROMPT_TEMPLATE_DIR": "prompts",
    "CUBE__BASE_URL": "http://cube:4000",
    "CUBE__API_SECRET": "test-cube-secret-at-least-32-chars!",
    "AUTH__OIDC_ISSUER": "",
    "AUTH__OIDC_AUDIENCE": "",
    "AUTH__JWKS_URL": "",
    "AUTH__DEV_STUB": "true",
    "AUTH__DEV_STUB_SECRET": _DEV_STUB_SECRET,
    "AUTH__TENANT_CLAIM": "tenant",
    "SEED_TENANT__SLUG": "local",
    "SEED_TENANT__NAME": "Local Tenant",
    "SEED_TENANT__ADMIN_EMAIL": "admin@local.test",
}

# Small CSV that produces a non-trivial payload for the pipeline to read back.
_CSV_BYTES = b"region,amount\nnortheast,100\nsouth,200\n"

# The tenant under test.
_SLUG = "acmecorp"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token(slug: str, *, exp_offset: int = 3600) -> str:
    """Sign an HS256 dev-stub JWT carrying the tenant claim."""
    payload = {
        "sub": "user-sub-e2e",
        "email": "e2e@example.com",
        "tenant": slug,
        "exp": int(time.time()) + exp_offset,
        "iat": int(time.time()),
    }
    return jwt.encode(payload, _DEV_STUB_SECRET, algorithm="HS256")


def _make_settings() -> Settings:
    """Build a Settings instance from _FAKE_ENV without disturbing os.environ."""
    import os

    original: dict[str, str | None] = {}
    for k, v in _FAKE_ENV.items():
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


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeObjectStore:
    """In-memory object store; same interface as the real one."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    async def put_object(self, *, key: str, body: bytes, content_type: str) -> None:
        self.objects[key] = (body, content_type)

    async def get_object(self, *, key: str) -> bytes:
        body, _ = self.objects[key]
        return body

    async def list_keys(self, *, prefix: str) -> list[str]:
        return [k for k in self.objects if k.startswith(prefix)]


@dataclass
class _FakeClickHouseE2E:
    """In-memory ClickHouse recording both DDL commands and read queries."""

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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _FAKE_ENV.items():
        monkeypatch.setenv(key, value)


@pytest.fixture()
def fake_store() -> _FakeObjectStore:
    return _FakeObjectStore()


@pytest.fixture()
def fake_clickhouse() -> _FakeClickHouseE2E:
    return _FakeClickHouseE2E()


@pytest.fixture()
def client_with_db(
    session: AsyncSession,
    fake_store: _FakeObjectStore,
    fake_clickhouse: _FakeClickHouseE2E,
) -> TestClient:  # type: ignore[return]
    """TestClient with in-memory DB + fake store + fake ClickHouse wired into the app."""
    from app.core.clickhouse import get_clickhouse_client
    from app.core.config import get_settings
    from app.core.db import get_db
    from app.core.object_store import get_object_store
    from app.main import app
    from app.tenancy.registry import TenantRegistry, get_tenant_registry

    get_settings.cache_clear()

    async def _fake_db() -> Any:
        yield session

    async def _fake_registry() -> Any:
        return TenantRegistry(session)

    def _fake_object_store() -> Any:
        return fake_store

    def _fake_clickhouse_client() -> Any:
        return fake_clickhouse

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_tenant_registry] = _fake_registry
    app.dependency_overrides[get_object_store] = _fake_object_store
    app.dependency_overrides[get_clickhouse_client] = _fake_clickhouse_client

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c  # type: ignore[misc]

    app.dependency_overrides.clear()
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# (1)-(5) Full vertical slice
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_vertical_slice_single_tenant(
    client_with_db: TestClient,
    session: AsyncSession,
    fake_store: _FakeObjectStore,
    fake_clickhouse: _FakeClickHouseE2E,
    make_tenant: Any,
) -> None:
    """CSV upload → pipeline → ClickHouse register → query, single tenant end-to-end.

    Each seam is asserted in sequence: bytes flow through upload into the store, the
    pipeline reads those exact bytes back, the register step issues tenant-scoped DDL,
    and the query endpoint hits only the tenant's own ClickHouse database.
    """
    resources = resources_for_slug(_SLUG)

    # -----------------------------------------------------------------------
    # (1) Setup: create tenant row + mint a token
    # -----------------------------------------------------------------------
    tenant = await make_tenant(_SLUG)
    token = _make_token(_SLUG)

    # -----------------------------------------------------------------------
    # (2) Upload: POST /api/v1/datasets/upload
    # -----------------------------------------------------------------------
    resp = client_with_db.post(
        "/api/v1/datasets/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("sales.csv", _CSV_BYTES, "text/csv")},
    )
    assert resp.status_code == 201, resp.text
    upload_body = resp.json()
    dataset_id = uuid.UUID(upload_body["id"])
    assert upload_body["original_filename"] == "sales.csv"
    assert upload_body["status"] == "uploaded"

    # The raw object key must be under the tenant's iceberg_namespace prefix.
    stored_keys = list(fake_store.objects)
    assert len(stored_keys) == 1
    object_key = stored_keys[0]
    assert object_key.startswith(f"{resources.iceberg_namespace}/")
    assert str(dataset_id) in object_key

    # The bytes are exactly what we uploaded — this is what the pipeline reads.
    assert fake_store.objects[object_key][0] == _CSV_BYTES

    # -----------------------------------------------------------------------
    # (3) Pipeline: CsvIcebergPipeline.run() on the real Dataset ORM row
    # -----------------------------------------------------------------------
    # Load the ORM row so tenant_id is the real UUID from the DB (isolation guard pass).
    result_row = await session.execute(
        select(Dataset).where(Dataset.id == dataset_id)
    )
    dataset_row: Dataset = result_row.scalar_one()
    assert dataset_row.tenant_id == tenant.id

    ctx = TenantContext(
        tenant_id=str(tenant.id),
        iceberg_namespace=resources.iceberg_namespace,
        clickhouse_db=resources.clickhouse_db,
        dbt_schema=resources.dbt_schema,
    )

    settings = _make_settings()
    pipeline = CsvIcebergPipeline(ctx=ctx, store=fake_store, settings=settings)

    # Patch _write_iceberg_table so no real pyiceberg/S3 I/O occurs.
    with patch.object(
        CsvIcebergPipeline, "_write_iceberg_table", autospec=True
    ) as mock_write:
        mock_write.return_value = 1  # row count, for pipeline metrics
        table_id = await pipeline.run(dataset_row)

    # Return value is "<namespace>.<table_name>".
    expected_table_name = _table_name_for_dataset(dataset_id)
    assert table_id == f"{resources.iceberg_namespace}.{expected_table_name}"

    # _write_iceberg_table received the exact bytes that upload stored.
    mock_write.assert_called_once()
    _, call_kwargs = mock_write.call_args
    assert call_kwargs["raw_bytes"] == _CSV_BYTES
    assert call_kwargs["table_name"] == expected_table_name

    # -----------------------------------------------------------------------
    # (4) Register: ClickHouseDatasetService.register_dataset
    # -----------------------------------------------------------------------
    iceberg_location = f"s3://test/{resources.iceberg_namespace}/{expected_table_name}"
    fake_catalog = _FakeCatalog(loc=iceberg_location)

    ch_service = ClickHouseDatasetService(ch=fake_clickhouse, settings=settings)
    with patch(
        "app.services.clickhouse_datasets.load_iceberg_catalog",
        return_value=fake_catalog,
    ):
        qualified = ch_service.register_dataset(ctx, dataset_row)

    # Returns "<db>.<table>".
    assert qualified == f"{resources.clickhouse_db}.{expected_table_name}"

    # Two DDL commands: CREATE DATABASE (unbound) + CREATE TABLE (unbound).
    assert len(fake_clickhouse.commands) == 2
    create_db_sql, create_db_bound = fake_clickhouse.commands[0]
    create_tbl_sql, create_tbl_bound = fake_clickhouse.commands[1]

    assert "CREATE DATABASE IF NOT EXISTS" in create_db_sql
    assert resources.clickhouse_db in create_db_sql
    assert create_db_bound is None

    assert "CREATE TABLE IF NOT EXISTS" in create_tbl_sql
    assert f"`{resources.clickhouse_db}`.`{expected_table_name}`" in create_tbl_sql
    assert "ENGINE = IcebergS3(" in create_tbl_sql
    assert create_tbl_bound is None

    # -----------------------------------------------------------------------
    # (5) Query: POST /api/v1/datasets/{id}/query
    # -----------------------------------------------------------------------
    fake_clickhouse.column_names = ["region", "total"]
    fake_clickhouse.rows = [("northeast", 100), ("south", 200)]

    query_resp = client_with_db.post(
        f"/api/v1/datasets/{dataset_id}/query",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "dimensions": ["region"],
            "metrics": [{"function": "sum", "column": "amount", "alias": "total"}],
            "filters": [{"column": "region", "op": "!=", "value": "west"}],
        },
    )
    assert query_resp.status_code == 200, query_resp.text
    qbody = query_resp.json()
    assert qbody["columns"] == ["region", "total"]
    assert qbody["rows"] == [["northeast", 100], ["south", 200]]
    assert qbody["row_count"] == 2

    # Exactly one query issued; it is read-only and bound to the tenant's database.
    assert len(fake_clickhouse.queries) == 1
    recorded_query = fake_clickhouse.queries[0]
    assert recorded_query["database"] == resources.clickhouse_db
    assert recorded_query["read_only"] is True

    # The filter value was passed as a bound parameter — never interpolated into SQL.
    assert recorded_query["parameters"] == {"p0": "west"}
    assert "'west'" not in recorded_query["sql"]

    # -----------------------------------------------------------------------
    # (5) End-to-end tenant-boundary consistency assertion
    # -----------------------------------------------------------------------
    # Namespace used by the pipeline, prefix of the stored object, and ClickHouse db
    # hit by the query all belong to the same single tenant.
    assert object_key.startswith(f"{resources.iceberg_namespace}/")
    assert table_id.startswith(f"{resources.iceberg_namespace}.")
    assert recorded_query["database"] == resources.clickhouse_db
    # All three come from the SAME resource map — no cross-tenant bleed possible.
    assert resources.iceberg_namespace == ctx.iceberg_namespace
    assert resources.clickhouse_db == ctx.clickhouse_db
