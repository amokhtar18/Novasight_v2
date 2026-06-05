"""Tests for the dispatcher: due-selection logic and broker wiring.

``select_due`` and ``list_enabled_reports`` live in service.py and need no broker.
The actor-wiring test sets a Dramatiq ``StubBroker`` before importing the schedule
module (whose ``@dramatiq.actor`` declarations require a broker) and asserts that
a due report is enqueued exactly once.
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.report_definition import ReportDefinition
from app.reporting.service import list_enabled_reports, select_due
from app.schemas.query import Metric, QueryRequest
from tests.conftest import MakeTenant
from tests.test_reporting_service import _make_dataset

_NOON_FRI = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)


def test_select_due_picks_enabled_and_due() -> None:
    due = SimpleNamespace(id=uuid.uuid4(), schedule="0 12 * * *", enabled=True)
    not_due = SimpleNamespace(id=uuid.uuid4(), schedule="0 0 * * *", enabled=True)
    disabled = SimpleNamespace(id=uuid.uuid4(), schedule="0 12 * * *", enabled=False)

    result = select_due([due, not_due, disabled], _NOON_FRI)

    assert result == [due.id]


def test_select_due_skips_invalid_schedule() -> None:
    good = SimpleNamespace(id=uuid.uuid4(), schedule="* * * * *", enabled=True)
    broken = SimpleNamespace(id=uuid.uuid4(), schedule="not a cron", enabled=True)

    # The invalid one is skipped (logged), not fatal to the whole tick.
    assert select_due([good, broken], _NOON_FRI) == [good.id]


@pytest.mark.asyncio
async def test_list_enabled_reports_returns_only_enabled(
    session: AsyncSession, make_tenant: MakeTenant
) -> None:
    tenant = await make_tenant("alpha")
    dataset = await _make_dataset(session, tenant.id)
    spec = QueryRequest(metrics=[Metric(function="count")]).model_dump()

    enabled = ReportDefinition(
        id=uuid.uuid4(), tenant_id=tenant.id, dataset_id=dataset.id, name="on",
        query_spec=spec, schedule="* * * * *", recipients=["a@alpha.test"], enabled=True,
    )
    disabled = ReportDefinition(
        id=uuid.uuid4(), tenant_id=tenant.id, dataset_id=dataset.id, name="off",
        query_spec=spec, schedule="* * * * *", recipients=["a@alpha.test"], enabled=False,
    )
    session.add_all([enabled, disabled])
    await session.flush()

    reports = await list_enabled_reports(session)

    assert {r.id for r in reports} == {enabled.id}


# ---------------------------------------------------------------------------
# Broker wiring — StubBroker + env must be set before importing the schedule module
# ---------------------------------------------------------------------------

_WORKER_ENV: dict[str, str] = {
    "ENVIRONMENT": "test",
    "POSTGRES__HOST": "localhost",
    "POSTGRES__USER": "test",
    "POSTGRES__PASSWORD": "test",
    "POSTGRES__DB": "test",
    "REDIS__HOST": "localhost",
    "OBJECT_STORE__ENDPOINT_URL": "http://localhost:9000",
    "OBJECT_STORE__ACCESS_KEY": "k",
    "OBJECT_STORE__SECRET_KEY": "s",
    "OBJECT_STORE__BUCKET": "b",
    "ICEBERG__CATALOG_URI": "http://localhost:8181",
    "ICEBERG__WAREHOUSE": "s3://b/warehouse",
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


def test_dispatch_enqueues_due_reports(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _WORKER_ENV.items():
        monkeypatch.setenv(key, value)

    import dramatiq
    from dramatiq.brokers.stub import StubBroker
    from periodiq import PeriodiqMiddleware

    from app.core.config import get_settings

    get_settings.cache_clear()
    broker = StubBroker()
    # The dispatcher is an @actor(periodic=...) — its broker needs periodiq's middleware.
    broker.add_middleware(PeriodiqMiddleware())
    dramatiq.set_broker(broker)

    # Import only after a broker is registered.
    from app.reporting import schedule
    from app.reporting.actors import render_and_send_report

    sent: list[str] = []
    monkeypatch.setattr(render_and_send_report, "send", lambda report_id: sent.append(report_id))

    due = SimpleNamespace(id=uuid.uuid4(), schedule="* * * * *", enabled=True)
    not_due = SimpleNamespace(id=uuid.uuid4(), schedule="0 0 1 1 *", enabled=True)

    async def _fake_list(_db: object) -> list[SimpleNamespace]:
        return [due, not_due]

    @asynccontextmanager
    async def _fake_scope(settings: object = None):  # type: ignore[no-untyped-def]
        yield object()

    monkeypatch.setattr(schedule, "list_enabled_reports", _fake_list)
    monkeypatch.setattr(schedule, "session_scope", _fake_scope)

    asyncio.run(schedule._dispatch(_NOON_FRI))

    assert sent == [str(due.id)]

    get_settings.cache_clear()
