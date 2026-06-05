"""Tests for column encryption in the ingestion path (Phase 5.4).

Covers:
  (a) the Arrow column-encryption helper encrypts only tagged columns;
  (b) the pipeline writes ciphertext at rest for tagged columns (decrypts back);
  (c) no plaintext sensitive value is emitted to logs during ingestion.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pyarrow as pa
import pytest
from pyiceberg.exceptions import NoSuchTableError

from app.core.crypto import LocalAesGcmProvider, decrypt_value, is_encrypted
from app.ingestion.csv_iceberg import CsvIcebergPipeline
from app.ingestion.encryption import encrypt_arrow_columns
from app.tenancy.context import TenantContext
from app.tenancy.resources import resources_for_slug
from tests.test_ingestion import _FakeObjectStore, _make_settings

_KEY = b"\x07" * 32
_CSV = b"id,ssn,name\n1,111-22-3333,Alice\n2,444-55-6666,Bob\n"


def _provider() -> LocalAesGcmProvider:
    return LocalAesGcmProvider(_KEY)


def _ctx(slug: str = "alpha") -> TenantContext:
    res = resources_for_slug(slug)
    return TenantContext(
        tenant_id=str(uuid.uuid4()),
        iceberg_namespace=res.iceberg_namespace,
        clickhouse_db=res.clickhouse_db,
        dbt_schema=res.dbt_schema,
    )


@dataclass
class _Dataset:
    id: uuid.UUID
    tenant_id: uuid.UUID
    object_key: str
    sensitive_columns: list[str] | None = None


# ---------------------------------------------------------------------------
# (a) helper
# ---------------------------------------------------------------------------


def test_encrypt_arrow_columns_only_touches_tagged() -> None:
    table = pa.table({"ssn": ["111-22-3333", "444-55-6666"], "name": ["Alice", "Bob"]})
    provider = _provider()

    out = encrypt_arrow_columns(table, ["ssn"], provider)

    ssn_values = out.column("ssn").to_pylist()
    name_values = out.column("name").to_pylist()
    # Tagged column is ciphertext that round-trips; untagged column is untouched.
    assert all(is_encrypted(v) for v in ssn_values)
    assert [decrypt_value(provider, v) for v in ssn_values] == ["111-22-3333", "444-55-6666"]
    assert name_values == ["Alice", "Bob"]


def test_encrypt_arrow_columns_skips_missing_and_nulls() -> None:
    table = pa.table({"ssn": ["x", None]})
    out = encrypt_arrow_columns(table, ["ssn", "absent"], _provider())
    values = out.column("ssn").to_pylist()
    assert is_encrypted(values[0])
    assert values[1] is None  # null preserved


# ---------------------------------------------------------------------------
# (b) pipeline writes ciphertext at rest
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_encrypts_tagged_columns_at_rest() -> None:
    ctx = _ctx()
    settings = _make_settings()
    store = _FakeObjectStore()
    provider = _provider()

    dataset_id = uuid.uuid4()
    object_key = f"{ctx.iceberg_namespace}/raw/datasets/{dataset_id}/data.csv"
    await store.put_object(key=object_key, body=_CSV, content_type="text/csv")
    dataset = _Dataset(
        id=dataset_id,
        tenant_id=uuid.UUID(ctx.tenant_id),
        object_key=object_key,
        sensitive_columns=["ssn"],
    )

    fake_table = MagicMock()
    fake_catalog = MagicMock()
    fake_catalog.create_table = MagicMock(return_value=fake_table)
    fake_catalog.load_table = MagicMock(side_effect=NoSuchTableError())

    pipeline = CsvIcebergPipeline(ctx=ctx, store=store, settings=settings, provider=provider)

    with patch.object(CsvIcebergPipeline, "_build_catalog_properties", return_value={}), patch(
        "pyiceberg.catalog.load_catalog", return_value=fake_catalog
    ):
        await pipeline.run(dataset)  # type: ignore[arg-type]

    # The Arrow table handed to create_table has the ssn column encrypted at rest.
    written_schema = fake_catalog.create_table.call_args.kwargs["schema"]
    written_table = fake_table.overwrite.call_args.args[0]
    assert "ssn" in written_schema.names
    ssn_values = written_table.column("ssn").to_pylist()
    assert all(is_encrypted(v) for v in ssn_values)
    assert [decrypt_value(provider, v) for v in ssn_values] == ["111-22-3333", "444-55-6666"]
    # The non-sensitive column stays plaintext.
    assert written_table.column("name").to_pylist() == ["Alice", "Bob"]


# ---------------------------------------------------------------------------
# (c) no plaintext sensitive value reaches the logs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingestion_does_not_log_plaintext(caplog: pytest.LogCaptureFixture) -> None:
    ctx = _ctx()
    settings = _make_settings()
    store = _FakeObjectStore()

    dataset_id = uuid.uuid4()
    object_key = f"{ctx.iceberg_namespace}/raw/datasets/{dataset_id}/data.csv"
    await store.put_object(key=object_key, body=_CSV, content_type="text/csv")
    dataset = _Dataset(
        id=dataset_id,
        tenant_id=uuid.UUID(ctx.tenant_id),
        object_key=object_key,
        sensitive_columns=["ssn"],
    )

    pipeline = CsvIcebergPipeline(ctx=ctx, store=store, settings=settings, provider=_provider())

    with caplog.at_level(logging.DEBUG), patch.object(
        CsvIcebergPipeline, "_build_catalog_properties", return_value={}
    ), patch("pyiceberg.catalog.load_catalog", return_value=MagicMock()):
        await pipeline.run(dataset)  # type: ignore[arg-type]

    # The plaintext SSNs never appear in any emitted log record.
    assert "111-22-3333" not in caplog.text
    assert "444-55-6666" not in caplog.text
