"""Tests for the KPI dispatcher: due selection and broker wiring."""
from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.kpi_threshold import KpiThreshold
from app.reporting.alerts.service import list_enabled_kpis, select_due
from app.schemas.query import Metric, QueryRequest
from tests.conftest import MakeTenant
from tests.test_reporting_dispatch import _WORKER_ENV
from tests.test_reporting_service import _make_dataset

_NOON_FRI = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)


def test_select_due_picks_enabled_and_due() -> None:
    due = SimpleNamespace(id=uuid.uuid4(), schedule="0 12 * * *", enabled=True)
    not_due = SimpleNamespace(id=uuid.uuid4(), schedule="0 0 * * *", enabled=True)
    disabled = SimpleNamespace(id=uuid.uuid4(), schedule="0 12 * * *", enabled=False)

    assert select_due([due, not_due, disabled], _NOON_FRI) == [due.id]


def test_select_due_skips_invalid_schedule() -> None:
    good = SimpleNamespace(id=uuid.uuid4(), schedule="* * * * *", enabled=True)
    broken = SimpleNamespace(id=uuid.uuid4(), schedule="nonsense", enabled=True)
    assert select_due([good, broken], _NOON_FRI) == [good.id]


@pytest.mark.asyncio
async def test_list_enabled_kpis_returns_only_enabled(
    session: AsyncSession, make_tenant: MakeTenant
) -> None:
    tenant = await make_tenant("alpha")
    dataset = await _make_dataset(session, tenant.id)
    spec = QueryRequest(metrics=[Metric(function="count", alias="v")]).model_dump()

    def _kpi(name: str, enabled: bool) -> KpiThreshold:
        return KpiThreshold(
            id=uuid.uuid4(), tenant_id=tenant.id, dataset_id=dataset.id, name=name,
            query_spec=spec, comparator=">", threshold=1.0, schedule="* * * * *",
            channel="email", recipients=["a@alpha.test"], enabled=enabled,
        )

    session.add_all([_kpi("on", True), _kpi("off", False)])
    await session.flush()

    kpis = await list_enabled_kpis(session)
    names = {k.name for k in kpis}
    assert names == {"on"}


def test_dispatch_enqueues_due_kpis(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _WORKER_ENV.items():
        monkeypatch.setenv(key, value)

    import dramatiq
    from dramatiq.brokers.stub import StubBroker
    from periodiq import PeriodiqMiddleware

    from app.core.config import get_settings

    get_settings.cache_clear()
    broker = StubBroker()
    broker.add_middleware(PeriodiqMiddleware())
    dramatiq.set_broker(broker)

    from app.reporting.alerts import schedule
    from app.reporting.alerts.actors import evaluate_kpi

    sent: list[str] = []
    monkeypatch.setattr(evaluate_kpi, "send", lambda kpi_id: sent.append(kpi_id))

    due = SimpleNamespace(id=uuid.uuid4(), schedule="* * * * *", enabled=True)
    not_due = SimpleNamespace(id=uuid.uuid4(), schedule="0 0 1 1 *", enabled=True)

    async def _fake_list(_db: object) -> list[SimpleNamespace]:
        return [due, not_due]

    @asynccontextmanager
    async def _fake_scope(settings: object = None):  # type: ignore[no-untyped-def]
        yield object()

    monkeypatch.setattr(schedule, "list_enabled_kpis", _fake_list)
    monkeypatch.setattr(schedule, "session_scope", _fake_scope)

    asyncio.run(schedule._dispatch(_NOON_FRI))

    assert sent == [str(due.id)]
    get_settings.cache_clear()
