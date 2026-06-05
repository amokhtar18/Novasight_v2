"""Tenant-scoped orchestration for scheduled reports.

``ReportService.run_report`` is the end-to-end job body: load the report
definition, **re-resolve the tenant scope from the registry** (golden rule 2),
run the stored structured query bound to that tenant's ClickHouse database, render
the result to ``.xlsx``, store it under the tenant's object-store prefix, and email
it to the report's recipients.

Tenant isolation is enforced in depth:

* the scope comes from ``resolve_tenant_context_for_job`` (server-side, never the
  work item's payload);
* ``ClickHouseDatasetService.run_aggregation`` both binds the query to the tenant
  database *and* asserts the dataset belongs to the resolved tenant — so a
  mis-pointed ``report_definitions`` row fails closed instead of reading another
  tenant's data;
* the rendered file's object key is prefixed with the tenant namespace.

Construction takes already-wired collaborators so the orchestration is trivially
testable with fakes; ``build_report_service`` assembles the real ones from
settings for the worker.
"""
from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings, get_settings
from app.core.object_store import ObjectStore
from app.core.sensitive import apply_to_rows
from app.models.report_definition import ReportDefinition
from app.reporting import cron
from app.reporting.email import EmailAttachment, EmailSender
from app.reporting.excel import XLSX_CONTENT_TYPE, render_workbook
from app.schemas.query import QueryRequest
from app.services.clickhouse_datasets import ClickHouseDatasetService
from app.tenancy.context import TenantContext
from app.tenancy.job_context import resolve_tenant_context_for_job

logger = logging.getLogger(__name__)


class ReportNotFoundError(LookupError):
    """The requested report definition does not exist."""


class ReportingNotConfiguredError(RuntimeError):
    """Reporting was invoked but its required configuration (SMTP) is absent."""


@dataclass(frozen=True)
class ReportRunResult:
    """Outcome of one report run — what was produced and where it went."""

    report_id: str
    object_key: str
    row_count: int
    recipients: list[str]


def _filename_slug(name: str) -> str:
    """A filesystem-safe slug for a report name (for the attachment filename)."""
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-").lower()
    return slug or "report"


def select_due(reports: Sequence[ReportDefinition], when: datetime) -> list[uuid.UUID]:
    """Return the ids of enabled reports whose cron schedule is due at ``when``.

    Pure: this is the dispatcher's decision, separated from enqueuing so it can be
    tested without a broker. A report with an unparseable schedule is skipped (and
    logged) rather than aborting the whole dispatch tick.
    """
    due: list[uuid.UUID] = []
    for report in reports:
        if not report.enabled:
            continue
        try:
            if cron.matches(report.schedule, when):
                due.append(report.id)
        except cron.CronError:
            logger.exception("Skipping report %s: invalid schedule %r", report.id, report.schedule)
    return due


async def list_enabled_reports(db: AsyncSession) -> Sequence[ReportDefinition]:
    """Load all enabled report definitions across tenants (schedule-scan, control plane).

    Reading the *registry* of schedules is control-plane metadata, not tenant data;
    each enqueued run re-resolves and enforces its own tenant scope before touching
    any tenant data.
    """
    result = await db.execute(
        select(ReportDefinition).where(ReportDefinition.enabled.is_(True))
    )
    return result.scalars().all()


class ReportService:
    """Render and deliver one tenant's scheduled report."""

    def __init__(
        self,
        ch_service: ClickHouseDatasetService,
        object_store: ObjectStore,
        email_sender: EmailSender,
        settings: Settings,
    ) -> None:
        self._ch = ch_service
        self._object_store = object_store
        self._email = email_sender
        self._settings = settings

    async def run_report(self, db: AsyncSession, report_id: uuid.UUID) -> ReportRunResult:
        """Execute the full render-and-send path for ``report_id``."""
        report = await self._load(db, report_id)

        # Re-derive the tenant scope from the authoritative registry — never from
        # the work item. Fails closed if the tenant is missing/suspended.
        ctx = await resolve_tenant_context_for_job(report.tenant.slug, db)

        request = QueryRequest.model_validate(report.query_spec)
        # Tenant-scoped query; also asserts the dataset belongs to this tenant.
        result = self._ch.run_aggregation(ctx, report.dataset, request)

        # Scheduled reports have no interactive principal, so sensitive columns are
        # always masked — a report can never become a back door around access control.
        sensitive = set(report.dataset.sensitive_columns or [])
        rows = apply_to_rows(
            result.column_names, result.rows, sensitive, reveal=False, provider=None
        )

        workbook = render_workbook(report.name, result.column_names, rows)

        object_key = self._object_key(ctx, report)
        await self._object_store.put_object(
            key=object_key, body=workbook, content_type=XLSX_CONTENT_TYPE
        )

        recipients = list(report.recipients)
        self._email.send(
            subject=f"{self._settings.reporting.subject_prefix}{report.name}",
            recipients=recipients,
            body=(
                f"Your scheduled report '{report.name}' is attached "
                f"({len(result.rows)} rows)."
            ),
            attachment=EmailAttachment(
                filename=f"{_filename_slug(report.name)}.xlsx", content=workbook
            ),
        )

        logger.info(
            "Report %s rendered for tenant=%s rows=%d key=%s recipients=%d",
            report.id,
            report.tenant.slug,
            len(result.rows),
            object_key,
            len(recipients),
        )
        return ReportRunResult(
            report_id=str(report.id),
            object_key=object_key,
            row_count=len(result.rows),
            recipients=recipients,
        )

    async def _load(self, db: AsyncSession, report_id: uuid.UUID) -> ReportDefinition:
        result = await db.execute(
            select(ReportDefinition)
            .where(ReportDefinition.id == report_id)
            .options(
                selectinload(ReportDefinition.tenant),
                selectinload(ReportDefinition.dataset),
            )
        )
        report = result.scalars().first()
        if report is None:
            raise ReportNotFoundError(f"report {report_id} not found")
        return report

    def _object_key(self, ctx: TenantContext, report: ReportDefinition) -> str:
        """Build the tenant-prefixed object key the rendered workbook is stored under."""
        stamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        prefix = self._settings.reporting.storage_prefix
        # Tenant namespace first → isolation is structural, not just by convention.
        return f"{ctx.iceberg_namespace}/{prefix}/{report.id}/{stamp}.xlsx"


def build_report_service(settings: Settings | None = None) -> ReportService:
    """Assemble a ``ReportService`` with real collaborators from settings (worker use).

    Raises ``ReportingNotConfiguredError`` if SMTP is not configured, so the worker
    fails closed with a clear message instead of silently producing nothing.
    """
    settings = settings or get_settings()
    if settings.smtp is None:
        raise ReportingNotConfiguredError(
            "SMTP__* is not configured; scheduled reporting cannot send email"
        )
    # Imported lazily so the request path / tests that never run reports don't pay
    # for constructing live infrastructure clients.
    from app.core.clickhouse import ConnectClickHouseClient
    from app.core.object_store import S3ObjectStore
    from app.reporting.email import SmtpEmailSender

    ch_service = ClickHouseDatasetService(
        ch=ConnectClickHouseClient(settings.clickhouse), settings=settings
    )
    return ReportService(
        ch_service=ch_service,
        object_store=S3ObjectStore(settings.object_store),
        email_sender=SmtpEmailSender(settings.smtp),
        settings=settings,
    )
