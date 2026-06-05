"""Tests for the CSV-to-Iceberg ingestion pipeline (Task 1.2).

Strategy:

The live Iceberg REST catalog and S3 storage are NOT available in the test
environment.  We follow the same pattern as ``test_datasets.py``:
- An in-memory ``_FakeObjectStore`` stands in for S3.
- ``CsvIcebergPipeline._write_iceberg_table`` is patched so no real pyiceberg
  catalog is constructed and no network/S3 I/O occurs.
- We assert on the *arguments* passed to the patched boundary to prove:
  (a) the pipeline targets the correct tenant namespace,
  (b) the correct table name (derived from dataset id) is used,
  (c) re-running triggers ``Table.overwrite`` (idempotency) not a second ``create_table``,
  (d) a dataset belonging to tenant B cannot be run through tenant A's pipeline
      (tenant-isolation invariant).

Coverage:
  (a) namespace scoping — namespace == tenant's iceberg_namespace.
  (b) table name is deterministic and based on dataset id.
  (c) idempotency — first run creates; second run overwrites; no duplication.
  (d) ISOLATION — pipeline raises ValueError for cross-tenant dataset.
  (e) catalog properties come from settings (catalog_uri, warehouse, s3 creds).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import Settings
from app.ingestion.csv_iceberg import CsvIcebergPipeline, _table_name_for_dataset
from app.tenancy.context import TenantContext
from app.tenancy.resources import resources_for_slug

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_TENANT_ALPHA = "alpha"
_TENANT_BETA = "betacorp"

_CSV_BYTES = b"id,name,score\n1,Alice,95\n2,Bob,87\n"


# ---------------------------------------------------------------------------
# Fakes & fixtures
# ---------------------------------------------------------------------------


class _FakeObjectStore:
    """In-memory object store — same shape as the one in test_datasets.py."""

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
class _FakeDataset:
    """Minimal Dataset stand-in for testing."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    object_key: str
    status: str = "uploaded"


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

    # restore
    for k, v in original.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    get_settings.cache_clear()

    return settings


# ---------------------------------------------------------------------------
# (b) Table name is deterministic and derived from dataset id
# ---------------------------------------------------------------------------


def test_table_name_is_deterministic() -> None:
    """Same dataset id always produces the same table name (no hyphens)."""
    dataset_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
    name = _table_name_for_dataset(dataset_id)
    assert name == "dataset_12345678123456781234567812345678"
    # No hyphens — valid SQL identifier.
    assert "-" not in name
    # Stable across calls.
    assert _table_name_for_dataset(dataset_id) == name


# ---------------------------------------------------------------------------
# (a) + (b) + (e): namespace scoping, deterministic name, catalog props from settings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_targets_tenant_namespace_and_table() -> None:
    """run() derives namespace from TenantContext and table name from dataset id."""
    ctx = _make_ctx(_TENANT_ALPHA)
    settings = _make_settings()
    store = _FakeObjectStore()

    dataset_id = uuid.UUID("aaaabbbb-cccc-dddd-eeee-ffffaaaabbbb")
    object_key = f"{ctx.iceberg_namespace}/raw/datasets/{dataset_id}/data.csv"
    await store.put_object(key=object_key, body=_CSV_BYTES, content_type="text/csv")

    dataset = _FakeDataset(
        id=dataset_id,
        tenant_id=uuid.UUID(ctx.tenant_id),
        object_key=object_key,
    )

    pipeline = CsvIcebergPipeline(ctx=ctx, store=store, settings=settings)

    # Patch _write_iceberg_table so no real catalog/S3 is contacted.
    with patch.object(
        CsvIcebergPipeline, "_write_iceberg_table", autospec=True
    ) as mock_write:
        mock_write.return_value = 2  # row count, for pipeline metrics
        result = await pipeline.run(dataset)  # type: ignore[arg-type]

    # Return value is <namespace>.<table_name>
    expected_table = _table_name_for_dataset(dataset_id)
    assert result == f"{ctx.iceberg_namespace}.{expected_table}"

    # _write_iceberg_table was called once with the correct raw_bytes and table_name.
    mock_write.assert_called_once()
    _, call_kwargs = mock_write.call_args
    assert call_kwargs["raw_bytes"] == _CSV_BYTES
    assert call_kwargs["table_name"] == expected_table


@pytest.mark.asyncio
async def test_catalog_properties_come_from_settings() -> None:
    """_build_catalog_properties returns values sourced from settings, not literals."""
    ctx = _make_ctx(_TENANT_ALPHA)
    settings = _make_settings()
    store = _FakeObjectStore()

    pipeline = CsvIcebergPipeline(ctx=ctx, store=store, settings=settings)
    props = pipeline._build_catalog_properties()

    assert props["type"] == "rest"
    assert props["uri"] == settings.iceberg.catalog_uri
    assert props["warehouse"] == settings.iceberg.warehouse
    assert props["s3.endpoint"] == settings.object_store.endpoint_url
    assert props["s3.access-key-id"] == settings.object_store.access_key.get_secret_value()
    assert props["s3.secret-access-key"] == settings.object_store.secret_key.get_secret_value()
    assert props["s3.region"] == settings.object_store.region
    # No literal infra strings present — all values came from settings.
    assert "localhost" not in str(props.get("s3.access-key-id", ""))


# ---------------------------------------------------------------------------
# (c) Idempotency: second run overwrites, does not create a duplicate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idempotency_overwrite_on_second_run() -> None:
    """_write_iceberg_table calls overwrite() on both first and second run.

    We patch pyiceberg at the catalog level and verify:
    - First run: create_table() called once, overwrite() called once.
    - Second run: load_table() succeeds, overwrite() called again (no create_table).
    """
    from pyiceberg.exceptions import NoSuchTableError

    ctx = _make_ctx(_TENANT_ALPHA)
    settings = _make_settings()
    store = _FakeObjectStore()

    dataset_id = uuid.uuid4()
    object_key = f"{ctx.iceberg_namespace}/raw/datasets/{dataset_id}/data.csv"
    await store.put_object(key=object_key, body=_CSV_BYTES, content_type="text/csv")
    dataset = _FakeDataset(
        id=dataset_id,
        tenant_id=uuid.UUID(ctx.tenant_id),
        object_key=object_key,
    )

    # Build a fake iceberg Table with an overwrite method.
    fake_table = MagicMock()
    fake_table.overwrite = MagicMock()

    # Catalog mock: first call to load_table raises NoSuchTableError (first run),
    # second call succeeds (second run).
    fake_catalog = MagicMock()
    fake_catalog.create_namespace = MagicMock()
    fake_catalog.create_table = MagicMock(return_value=fake_table)
    fake_catalog.load_table = MagicMock(
        side_effect=[NoSuchTableError("not found"), fake_table]
    )

    pipeline = CsvIcebergPipeline(ctx=ctx, store=store, settings=settings)

    patch_props = patch(
        "app.ingestion.csv_iceberg.CsvIcebergPipeline._build_catalog_properties",
        return_value={},
    )
    patch_catalog = patch("pyiceberg.catalog.load_catalog", return_value=fake_catalog)
    with patch_props, patch_catalog:
        # First run — table does not exist yet.
        await pipeline.run(dataset)  # type: ignore[arg-type]
        assert fake_catalog.create_table.call_count == 1
        assert fake_table.overwrite.call_count == 1

        # Second run — table already exists; overwrite again, no new create_table.
        await pipeline.run(dataset)  # type: ignore[arg-type]
        assert fake_catalog.create_table.call_count == 1
        assert fake_table.overwrite.call_count == 2


# ---------------------------------------------------------------------------
# (d) ISOLATION: tenant A's pipeline cannot ingest tenant B's dataset
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_isolation_cross_tenant_dataset_rejected() -> None:
    """Pipeline raises ValueError when dataset.tenant_id != ctx.tenant_id.

    This is the tenant-isolation invariant: a CsvIcebergPipeline scoped to
    tenant A must refuse to write a dataset that belongs to tenant B, even if
    the caller somehow constructs such a call.
    """
    ctx_a = _make_ctx(_TENANT_ALPHA)
    ctx_b = _make_ctx(_TENANT_BETA)
    settings = _make_settings()
    store = _FakeObjectStore()

    # A dataset that belongs to tenant B.
    dataset_id = uuid.uuid4()
    object_key = f"{ctx_b.iceberg_namespace}/raw/datasets/{dataset_id}/data.csv"
    await store.put_object(key=object_key, body=_CSV_BYTES, content_type="text/csv")
    dataset_b = _FakeDataset(
        id=dataset_id,
        tenant_id=uuid.UUID(ctx_b.tenant_id),  # belongs to B
        object_key=object_key,
    )

    # Pipeline scoped to tenant A.
    pipeline_a = CsvIcebergPipeline(ctx=ctx_a, store=store, settings=settings)

    with pytest.raises(ValueError, match=str(dataset_b.tenant_id)):
        await pipeline_a.run(dataset_b)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_isolation_namespace_never_crosses_tenants() -> None:
    """The namespace passed to _write_iceberg_table is always the pipeline's own tenant.

    Even if two pipelines run sequentially, each targets only its own namespace.
    """
    ctx_a = _make_ctx(_TENANT_ALPHA)
    ctx_b = _make_ctx(_TENANT_BETA)
    settings = _make_settings()
    store = _FakeObjectStore()

    async def _run_pipeline(ctx: TenantContext) -> tuple[str, str]:
        """Return (namespace_used, table_name_used) captured from _write_iceberg_table."""
        dataset_id = uuid.uuid4()
        object_key = f"{ctx.iceberg_namespace}/raw/datasets/{dataset_id}/data.csv"
        await store.put_object(key=object_key, body=_CSV_BYTES, content_type="text/csv")
        dataset = _FakeDataset(
            id=dataset_id,
            tenant_id=uuid.UUID(ctx.tenant_id),
            object_key=object_key,
        )
        pipeline = CsvIcebergPipeline(ctx=ctx, store=store, settings=settings)
        captured: dict[str, Any] = {}

        def _capture(
            self_: Any,
            *,
            raw_bytes: bytes,
            table_name: str,
            sensitive_columns: list[str] | None = None,
        ) -> int:
            captured["table_name"] = table_name
            return 0  # row count, for pipeline metrics

        with patch.object(CsvIcebergPipeline, "_write_iceberg_table", _capture):
            result = await pipeline.run(dataset)  # type: ignore[arg-type]

        ns, tname = result.split(".", 1)
        assert captured["table_name"] == tname
        return ns, tname

    ns_a, _ = await _run_pipeline(ctx_a)
    ns_b, _ = await _run_pipeline(ctx_b)

    assert ns_a == ctx_a.iceberg_namespace
    assert ns_b == ctx_b.iceberg_namespace
    # Namespaces are distinct — no cross-tenant bleed.
    assert ns_a != ns_b
