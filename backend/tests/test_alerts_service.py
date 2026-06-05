"""Tests for KPI alert evaluation + exactly-once breach state (alerts/service.py).

Covers the Task 5.2 acceptance:
  (a) a breached threshold fires exactly one alert (no re-fire while still breaching);
  (b) recovery re-arms so the next breach alerts again;
  (c) thresholds/comparators are plain registry data — changing them changes behaviour
      with no code change;
  (d) ISOLATION — a KPI whose dataset belongs to another tenant fails closed.
"""
from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clickhouse import QueryResult
from app.core.config import Settings
from app.models.kpi_threshold import KpiThreshold
from app.reporting.alerts.channels import AlertChannel, AlertEvent
from app.reporting.alerts.service import (
    KpiAlertService,
    KpiNotFoundError,
    build_kpi_alert_service,
)
from app.schemas.query import Metric, QueryRequest
from app.services.clickhouse_datasets import ClickHouseDatasetService
from tests.conftest import MakeTenant
from tests.test_reporting_service import _BASE_ENV, _make_dataset


@dataclass
class _FakeClickHouse:
    column_names: list[str] = field(default_factory=lambda: ["v"])
    rows: list[tuple[Any, ...]] = field(default_factory=list)
    queries: list[dict[str, Any]] = field(default_factory=list)

    def command(self, sql: str, *, database: str | None = None) -> None:  # pragma: no cover
        raise AssertionError("KPI evaluation must never issue DDL/writes")

    def query(
        self, sql: str, *, database: str, parameters: Any = None, read_only: bool = True
    ) -> QueryResult:
        self.queries.append({"database": database, "read_only": read_only})
        return QueryResult(column_names=list(self.column_names), rows=list(self.rows))


@dataclass
class _RecordingChannel:
    events: list[AlertEvent] = field(default_factory=list)

    def send(self, event: AlertEvent) -> None:
        self.events.append(event)


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


def _build_service(
    settings: Settings, ch: _FakeClickHouse, channel: AlertChannel
) -> KpiAlertService:
    ch_service = ClickHouseDatasetService(ch=ch, settings=settings)  # type: ignore[arg-type]
    return KpiAlertService(
        ch_service=ch_service, settings=settings, channel_factory=lambda _kpi: channel
    )


async def _make_kpi(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    dataset_id: uuid.UUID,
    comparator: str = ">",
    threshold: float = 100.0,
) -> KpiThreshold:
    spec = QueryRequest(metrics=[Metric(function="sum", column="amount", alias="v")]).model_dump()
    kpi = KpiThreshold(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        name="Daily revenue",
        query_spec=spec,
        comparator=comparator,
        threshold=threshold,
        schedule="*/5 * * * *",
        channel="email",
        recipients=["ops@alpha.test"],
    )
    session.add(kpi)
    await session.flush()
    return kpi


# ---------------------------------------------------------------------------
# (a) + (b) Exactly-once lifecycle: fire once, no re-fire, recover, fire again
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_breach_fires_exactly_one_alert_and_rearms(
    session: AsyncSession, make_tenant: MakeTenant, settings: Settings
) -> None:
    tenant = await make_tenant("alpha")
    dataset = await _make_dataset(session, tenant.id)
    kpi = await _make_kpi(session, tenant_id=tenant.id, dataset_id=dataset.id, threshold=100.0)

    ch = _FakeClickHouse()
    channel = _RecordingChannel()
    service = _build_service(settings, ch, channel)

    # First breach (value 150 > 100) → one alert, bound to the tenant's own DB.
    ch.rows = [(150,)]
    r1 = await service.evaluate(session, kpi.id)
    assert r1.status == "fired" and r1.fired is True
    assert len(channel.events) == 1
    assert ch.queries[0]["database"] == "tenant_alpha"
    assert ch.queries[0]["read_only"] is True
    assert kpi.is_breaching is True
    assert kpi.last_fired_at is not None

    # Still breaching (value 200) → NO second alert. This is the exactly-once guarantee.
    ch.rows = [(200,)]
    r2 = await service.evaluate(session, kpi.id)
    assert r2.status == "still_breaching" and r2.fired is False
    assert len(channel.events) == 1

    # Recovery (value 50) → re-arm, still no alert.
    ch.rows = [(50,)]
    r3 = await service.evaluate(session, kpi.id)
    assert r3.status == "recovered" and r3.fired is False
    assert kpi.is_breaching is False
    assert len(channel.events) == 1

    # New breach after recovery → fires again (exactly one per episode).
    ch.rows = [(150,)]
    r4 = await service.evaluate(session, kpi.id)
    assert r4.status == "fired" and r4.fired is True
    assert len(channel.events) == 2


@dataclass
class _FailingChannel:
    """A channel whose delivery always fails, to test the persist-before-send order."""

    calls: int = 0

    def send(self, event: AlertEvent) -> None:
        self.calls += 1
        raise RuntimeError("delivery backend is down")


@pytest.mark.asyncio
async def test_breach_state_persists_even_when_delivery_fails(
    session: AsyncSession, make_tenant: MakeTenant, settings: Settings
) -> None:
    tenant = await make_tenant("alpha")
    dataset = await _make_dataset(session, tenant.id)
    kpi = await _make_kpi(session, tenant_id=tenant.id, dataset_id=dataset.id, threshold=100.0)

    ch = _FakeClickHouse(rows=[(150,)])
    channel = _FailingChannel()
    service = _build_service(settings, ch, channel)

    # Delivery raises, but the breach episode is recorded (state persisted first)...
    r1 = await service.evaluate(session, kpi.id)
    assert r1.status == "fired"
    assert kpi.is_breaching is True
    assert channel.calls == 1

    # ...so the next tick sees "still breaching" and does NOT re-attempt delivery.
    ch.rows = [(160,)]
    r2 = await service.evaluate(session, kpi.id)
    assert r2.status == "still_breaching"
    assert channel.calls == 1  # no duplicate send despite the earlier failure


@pytest.mark.asyncio
async def test_value_below_threshold_does_not_alert(
    session: AsyncSession, make_tenant: MakeTenant, settings: Settings
) -> None:
    tenant = await make_tenant("alpha")
    dataset = await _make_dataset(session, tenant.id)
    kpi = await _make_kpi(session, tenant_id=tenant.id, dataset_id=dataset.id, threshold=100.0)

    ch = _FakeClickHouse(rows=[(20,)])
    channel = _RecordingChannel()
    service = _build_service(settings, ch, channel)

    result = await service.evaluate(session, kpi.id)
    assert result.status == "ok" and result.fired is False
    assert channel.events == []
    assert kpi.is_breaching is False


@pytest.mark.asyncio
async def test_no_data_is_not_a_breach(
    session: AsyncSession, make_tenant: MakeTenant, settings: Settings
) -> None:
    tenant = await make_tenant("alpha")
    dataset = await _make_dataset(session, tenant.id)
    kpi = await _make_kpi(session, tenant_id=tenant.id, dataset_id=dataset.id)

    ch = _FakeClickHouse(rows=[])  # empty result
    channel = _RecordingChannel()
    service = _build_service(settings, ch, channel)

    result = await service.evaluate(session, kpi.id)
    assert result.status == "no_data" and result.fired is False
    assert channel.events == []


# ---------------------------------------------------------------------------
# (c) Threshold is plain registry data — a different comparator changes behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_comparator_is_config_driven(
    session: AsyncSession, make_tenant: MakeTenant, settings: Settings
) -> None:
    tenant = await make_tenant("alpha")
    dataset = await _make_dataset(session, tenant.id)
    # "less than 100" breach with value 50 — no code change, only registry data.
    kpi = await _make_kpi(
        session, tenant_id=tenant.id, dataset_id=dataset.id, comparator="<", threshold=100.0
    )

    ch = _FakeClickHouse(rows=[(50,)])
    channel = _RecordingChannel()
    service = _build_service(settings, ch, channel)

    result = await service.evaluate(session, kpi.id)
    assert result.status == "fired"
    assert len(channel.events) == 1


# ---------------------------------------------------------------------------
# (d) ISOLATION + not-found
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_tenant_dataset_is_rejected(
    session: AsyncSession, make_tenant: MakeTenant, settings: Settings
) -> None:
    tenant_a = await make_tenant("alpha")
    tenant_b = await make_tenant("betacorp")
    dataset_b = await _make_dataset(session, tenant_b.id)
    # KPI owned by A but pointing at B's dataset.
    kpi = await _make_kpi(session, tenant_id=tenant_a.id, dataset_id=dataset_b.id)

    ch = _FakeClickHouse(rows=[(150,)])
    channel = _RecordingChannel()
    service = _build_service(settings, ch, channel)

    with pytest.raises(ValueError, match=str(tenant_b.id)):
        await service.evaluate(session, kpi.id)

    # Fail closed: nothing queried, no alert, no state change.
    assert ch.queries == []
    assert channel.events == []
    assert kpi.is_breaching is False


@pytest.mark.asyncio
async def test_unknown_kpi_raises(session: AsyncSession, settings: Settings) -> None:
    service = _build_service(settings, _FakeClickHouse(), _RecordingChannel())
    with pytest.raises(KpiNotFoundError):
        await service.evaluate(session, uuid.uuid4())


def test_build_kpi_alert_service_smoke(settings: Settings) -> None:
    # The real factory assembles without touching infrastructure.
    service = build_kpi_alert_service(settings)
    assert isinstance(service, KpiAlertService)
