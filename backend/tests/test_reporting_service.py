"""Tests for the scheduled-report orchestration (app/reporting/service.py).

Covers the Task 5.1 acceptance:
  (a) a report run renders a tenant-scoped .xlsx, stores it under the tenant's
      object-store prefix, and emails it to the report's recipients;
  (b) the query is bound to the tenant's own ClickHouse database (read-only);
  (c) ISOLATION — a report whose dataset belongs to another tenant fails closed,
      with nothing queried, stored, or emailed.

No live infrastructure: ClickHouse, the object store, and SMTP are all fakes; the
control plane runs on the in-memory SQLite engine from conftest.
"""
from __future__ import annotations

import os
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clickhouse import QueryResult
from app.core.config import Settings
from app.models.dataset import Dataset
from app.models.report_definition import ReportDefinition
from app.reporting.email import EmailAttachment
from app.reporting.service import ReportService
from app.schemas.query import Metric, QueryRequest
from app.services.clickhouse_datasets import ClickHouseDatasetService
from tests.conftest import MakeTenant

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class _FakeClickHouse:
    column_names: list[str] = field(default_factory=list)
    rows: list[tuple[Any, ...]] = field(default_factory=list)
    queries: list[dict[str, Any]] = field(default_factory=list)
    commands: list[tuple[str, str | None]] = field(default_factory=list)

    def command(self, sql: str, *, database: str | None = None) -> None:
        self.commands.append((sql, database))

    def query(
        self, sql: str, *, database: str, parameters: Any = None, read_only: bool = True
    ) -> QueryResult:
        self.queries.append({"sql": sql, "database": database, "read_only": read_only})
        return QueryResult(column_names=list(self.column_names), rows=list(self.rows))


@dataclass
class _FakeObjectStore:
    objects: dict[str, bytes] = field(default_factory=dict)

    async def put_object(self, *, key: str, body: bytes, content_type: str) -> None:
        self.objects[key] = body

    async def get_object(self, *, key: str) -> bytes:
        return self.objects[key]

    async def list_keys(self, *, prefix: str) -> list[str]:
        return [k for k in self.objects if k.startswith(prefix)]


@dataclass
class _SentEmail:
    subject: str
    recipients: list[str]
    body: str
    attachment: EmailAttachment | None


@dataclass
class _FakeEmailSender:
    sent: list[_SentEmail] = field(default_factory=list)

    def send(
        self,
        *,
        subject: str,
        recipients: Sequence[str],
        body: str,
        attachment: EmailAttachment | None = None,
    ) -> None:
        self.sent.append(_SentEmail(subject, list(recipients), body, attachment))


# ---------------------------------------------------------------------------
# Settings + helpers
# ---------------------------------------------------------------------------

_BASE_ENV: dict[str, str] = {
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
    "SEED_TENANT__SLUG": "local",
    "SEED_TENANT__NAME": "Local",
    "SEED_TENANT__ADMIN_EMAIL": "admin@local.test",
}


@pytest.fixture
def settings() -> Iterator[Settings]:
    original = {k: os.environ.get(k) for k in _BASE_ENV}
    os.environ.update(_BASE_ENV)
    try:
        yield Settings()
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


async def _make_dataset(session: AsyncSession, tenant_id: uuid.UUID) -> Dataset:
    dataset = Dataset(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name="orders",
        original_filename="orders.csv",
        object_key=f"{tenant_id}/orders-{uuid.uuid4().hex}.csv",
        content_type="text/csv",
        size_bytes=123,
    )
    session.add(dataset)
    await session.flush()
    return dataset


async def _make_report(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    dataset_id: uuid.UUID,
    recipients: list[str],
) -> ReportDefinition:
    spec = QueryRequest(metrics=[Metric(function="count", alias="n")]).model_dump()
    report = ReportDefinition(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        name="Daily Orders",
        query_spec=spec,
        schedule="0 6 * * *",
        recipients=recipients,
    )
    session.add(report)
    await session.flush()
    return report


def _build_service(
    settings: Settings, ch: _FakeClickHouse, store: _FakeObjectStore, email: _FakeEmailSender
) -> ReportService:
    ch_service = ClickHouseDatasetService(ch=ch, settings=settings)  # type: ignore[arg-type]
    return ReportService(
        ch_service=ch_service, object_store=store, email_sender=email, settings=settings
    )


# ---------------------------------------------------------------------------
# (a) + (b) Happy path: tenant-scoped render → store → email
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_report_renders_stores_and_emails(
    session: AsyncSession, make_tenant: MakeTenant, settings: Settings
) -> None:
    tenant = await make_tenant("alpha")
    dataset = await _make_dataset(session, tenant.id)
    recipients = ["ceo@alpha.test", "ops@alpha.test"]
    report = await _make_report(
        session, tenant_id=tenant.id, dataset_id=dataset.id, recipients=recipients
    )

    ch = _FakeClickHouse(column_names=["region", "total"], rows=[("eu", 10), ("us", 20)])
    store = _FakeObjectStore()
    email = _FakeEmailSender()
    service = _build_service(settings, ch, store, email)

    result = await service.run_report(session, report.id)

    # The query ran bound to the tenant's own ClickHouse database, read-only.
    assert len(ch.queries) == 1
    assert ch.queries[0]["database"] == "tenant_alpha"
    assert ch.queries[0]["read_only"] is True

    # A workbook was stored under the tenant's namespace prefix.
    assert result.object_key.startswith(f"{tenant.slug}/reports/{report.id}/")
    assert result.object_key.endswith(".xlsx")
    assert set(store.objects) == {result.object_key}
    assert store.objects[result.object_key][:2] == b"PK"  # valid xlsx (zip) bytes

    # It was emailed to exactly the report's recipients, with the workbook attached.
    assert len(email.sent) == 1
    sent = email.sent[0]
    assert sent.recipients == recipients
    assert sent.subject == "[NovaSight] Daily Orders"
    assert sent.attachment is not None
    assert sent.attachment.filename.endswith(".xlsx")
    assert sent.attachment.content[:2] == b"PK"

    assert result.row_count == 2
    assert result.recipients == recipients


# ---------------------------------------------------------------------------
# (c) ISOLATION: a report pointing at another tenant's dataset fails closed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_report_cross_tenant_dataset_is_rejected(
    session: AsyncSession, make_tenant: MakeTenant, settings: Settings
) -> None:
    tenant_a = await make_tenant("alpha")
    tenant_b = await make_tenant("betacorp")

    # Dataset belongs to B; the report is owned by A but (mis)points at B's dataset.
    dataset_b = await _make_dataset(session, tenant_b.id)
    report = await _make_report(
        session, tenant_id=tenant_a.id, dataset_id=dataset_b.id, recipients=["x@alpha.test"]
    )

    ch = _FakeClickHouse(column_names=["n"], rows=[(1,)])
    store = _FakeObjectStore()
    email = _FakeEmailSender()
    service = _build_service(settings, ch, store, email)

    with pytest.raises(ValueError, match=str(tenant_b.id)):
        await service.run_report(session, report.id)

    # Fail closed: nothing queried, nothing stored, nothing emailed.
    assert ch.queries == []
    assert store.objects == {}
    assert email.sent == []


@pytest.mark.asyncio
async def test_run_report_missing_report_raises(
    session: AsyncSession, settings: Settings
) -> None:
    from app.reporting.service import ReportNotFoundError

    service = _build_service(settings, _FakeClickHouse(), _FakeObjectStore(), _FakeEmailSender())
    with pytest.raises(ReportNotFoundError):
        await service.run_report(session, uuid.uuid4())


# ---------------------------------------------------------------------------
# Phase 5.4 — scheduled reports mask sensitive columns (no interactive principal)
# ---------------------------------------------------------------------------


def _xlsx_shared_strings(data: bytes) -> str:
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if "xl/sharedStrings.xml" in archive.namelist():
            return archive.read("xl/sharedStrings.xml").decode("utf-8")
    return ""


@pytest.mark.asyncio
async def test_report_masks_sensitive_columns(
    session: AsyncSession, make_tenant: MakeTenant, settings: Settings
) -> None:
    tenant = await make_tenant("alpha")
    dataset = await _make_dataset(session, tenant.id)
    dataset.sensitive_columns = ["ssn"]
    await session.flush()
    report = await _make_report(
        session, tenant_id=tenant.id, dataset_id=dataset.id, recipients=["a@alpha.test"]
    )

    # Serving returns the column encrypted at rest; the report must mask it.
    stored_cipher = "enc:v1:ZZZopaqueTOKEN"
    ch = _FakeClickHouse(column_names=["ssn", "n"], rows=[(stored_cipher, 5)])
    store = _FakeObjectStore()
    service = _build_service(settings, ch, store, _FakeEmailSender())

    result = await service.run_report(session, report.id)

    strings = _xlsx_shared_strings(store.objects[result.object_key])
    # The mask is present; the stored ciphertext never reaches the workbook.
    assert "***" in strings
    assert stored_cipher not in strings
