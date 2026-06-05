"""Tenant-scoped KPI evaluation with exactly-once breach alerting (Phase 5.2).

``KpiAlertService.evaluate`` is the job body: load the KPI, re-resolve the tenant
scope from the registry (golden rule 2), run the stored aggregate bound to the
tenant's ClickHouse database, compare to the threshold, and — on the transition
from not-breaching to breaching — deliver **one** alert. The breach state lives on
the KPI row, so a sustained breach never re-fires and a recovery re-arms it.

Isolation in depth: the scope comes from ``resolve_tenant_context_for_job`` (never
the work item), and ``run_aggregation`` asserts the dataset belongs to the resolved
tenant, so a mis-pointed KPI fails closed instead of reading another tenant's data.
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings, get_settings
from app.models.kpi_threshold import KpiThreshold
from app.reporting import cron
from app.reporting.alerts.channels import AlertChannel, AlertEvent
from app.reporting.alerts.evaluator import extract_value, is_breached
from app.schemas.query import QueryRequest
from app.services.clickhouse_datasets import ClickHouseDatasetService
from app.tenancy.job_context import resolve_tenant_context_for_job

logger = logging.getLogger(__name__)

# A factory that builds the right delivery channel for a given KPI row.
ChannelFactory = Callable[[KpiThreshold], AlertChannel]


class KpiNotFoundError(LookupError):
    """The requested KPI threshold does not exist."""


class AlertingNotConfiguredError(RuntimeError):
    """A KPI requires delivery configuration (SMTP / webhook) that is absent."""


class AlertingError(RuntimeError):
    """A KPI is misconfigured (e.g. an unknown channel)."""


@dataclass(frozen=True)
class EvaluationResult:
    """Outcome of evaluating one KPI."""

    kpi_id: str
    status: str            # "fired" | "still_breaching" | "recovered" | "ok" | "no_data"
    fired: bool
    value: float | None


def select_due(kpis: Sequence[KpiThreshold], when: datetime) -> list[uuid.UUID]:
    """Return the ids of enabled KPIs whose cron schedule is due at ``when`` (pure)."""
    due: list[uuid.UUID] = []
    for kpi in kpis:
        if not kpi.enabled:
            continue
        try:
            if cron.matches(kpi.schedule, when):
                due.append(kpi.id)
        except cron.CronError:
            logger.exception("Skipping KPI %s: invalid schedule %r", kpi.id, kpi.schedule)
    return due


async def list_enabled_kpis(db: AsyncSession) -> Sequence[KpiThreshold]:
    """Load all enabled KPI thresholds across tenants (schedule scan, control plane)."""
    result = await db.execute(select(KpiThreshold).where(KpiThreshold.enabled.is_(True)))
    return result.scalars().all()


class KpiAlertService:
    """Evaluate one tenant's KPI and alert exactly once per breach episode."""

    def __init__(
        self,
        ch_service: ClickHouseDatasetService,
        settings: Settings,
        channel_factory: ChannelFactory,
    ) -> None:
        self._ch = ch_service
        self._settings = settings
        self._channel_factory = channel_factory

    async def evaluate(self, db: AsyncSession, kpi_id: uuid.UUID) -> EvaluationResult:
        """Evaluate ``kpi_id`` and, on a new breach, deliver exactly one alert."""
        kpi = await self._load(db, kpi_id)
        ctx = await resolve_tenant_context_for_job(kpi.tenant.slug, db)

        request = QueryRequest.model_validate(kpi.query_spec)
        # Tenant-scoped; also asserts the dataset belongs to this tenant.
        result = self._ch.run_aggregation(ctx, kpi.dataset, request)
        value = extract_value(result.column_names, result.rows)

        # Pass the public slug (not the internal ClickHouse DB name) into the alert.
        return await self._apply_state(db, kpi, value, tenant=kpi.tenant.slug)

    async def _apply_state(
        self, db: AsyncSession, kpi: KpiThreshold, value: float | None, *, tenant: str
    ) -> EvaluationResult:
        if value is None:
            logger.info("KPI %s produced no value; skipping", kpi.id)
            return EvaluationResult(str(kpi.id), "no_data", fired=False, value=None)

        breached = is_breached(value, kpi.comparator, kpi.threshold)

        if breached and not kpi.is_breaching:
            # Transition into breach. Persist the state transition BEFORE delivering,
            # so a delivery failure can never roll back the breach record and cause a
            # re-fire on the next tick (the exactly-once guarantee survives a flaky
            # SMTP/webhook). A delivery failure after this point is logged, not raised,
            # so a Dramatiq retry of this job cannot double-send.
            kpi.is_breaching = True
            kpi.last_fired_at = datetime.now(tz=UTC)
            await db.commit()

            event = AlertEvent(
                kpi_name=kpi.name,
                tenant=tenant,
                value=value,
                comparator=kpi.comparator,
                threshold=kpi.threshold,
            )
            try:
                self._channel_factory(kpi).send(event)
                logger.info("KPI %s breached (value=%s) — alert fired", kpi.id, value)
            except Exception:
                logger.exception(
                    "KPI %s breached but alert delivery failed (state already recorded)",
                    kpi.id,
                )
            return EvaluationResult(str(kpi.id), "fired", fired=True, value=value)

        if breached and kpi.is_breaching:
            # Still breaching — already alerted; do not re-fire.
            return EvaluationResult(str(kpi.id), "still_breaching", fired=False, value=value)

        if not breached and kpi.is_breaching:
            # Recovered — re-arm so the next breach alerts again.
            kpi.is_breaching = False
            await db.commit()
            logger.info("KPI %s recovered (value=%s)", kpi.id, value)
            return EvaluationResult(str(kpi.id), "recovered", fired=False, value=value)

        return EvaluationResult(str(kpi.id), "ok", fired=False, value=value)

    async def _load(self, db: AsyncSession, kpi_id: uuid.UUID) -> KpiThreshold:
        result = await db.execute(
            select(KpiThreshold)
            .where(KpiThreshold.id == kpi_id)
            .options(
                selectinload(KpiThreshold.tenant),
                selectinload(KpiThreshold.dataset),
            )
        )
        kpi = result.scalars().first()
        if kpi is None:
            raise KpiNotFoundError(f"KPI {kpi_id} not found")
        return kpi


def _default_channel_factory(settings: Settings) -> ChannelFactory:
    """Build the production channel factory: email via SMTP, or webhook via HTTP."""
    from app.reporting.alerts.channels import EmailAlertChannel, WebhookAlertChannel
    from app.reporting.email import SmtpEmailSender

    def factory(kpi: KpiThreshold) -> AlertChannel:
        if kpi.channel == "email":
            if settings.smtp is None:
                raise AlertingNotConfiguredError(
                    "SMTP__* is not configured; email KPI alerts cannot be sent"
                )
            return EmailAlertChannel(
                SmtpEmailSender(settings.smtp),
                kpi.recipients or [],
                settings.alerts.subject_prefix,
            )
        if kpi.channel == "webhook":
            if not kpi.webhook_url:
                raise AlertingNotConfiguredError(
                    f"KPI {kpi.id} uses the webhook channel but has no webhook_url"
                )
            return WebhookAlertChannel(
                kpi.webhook_url, settings.alerts.webhook_timeout_seconds
            )
        raise AlertingError(f"KPI {kpi.id} has unknown channel {kpi.channel!r}")

    return factory


def build_kpi_alert_service(settings: Settings | None = None) -> KpiAlertService:
    """Assemble a ``KpiAlertService`` with real collaborators from settings (worker use)."""
    settings = settings or get_settings()
    from app.core.clickhouse import ConnectClickHouseClient

    ch_service = ClickHouseDatasetService(
        ch=ConnectClickHouseClient(settings.clickhouse), settings=settings
    )
    return KpiAlertService(
        ch_service=ch_service,
        settings=settings,
        channel_factory=_default_channel_factory(settings),
    )
