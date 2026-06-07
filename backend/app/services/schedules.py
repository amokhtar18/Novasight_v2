"""Pipeline schedule logic: tenant-scoped CRUD + control-plane due dispatch (#4).

Schedules are tenant config (a cron + a target pipeline). The periodiq dispatcher
calls ``create_due_runs`` each heartbeat: it scans *enabled* schedules across tenants,
finds those due at this minute, and for each enqueues a pipeline run through the same
worker path as run-now. Reading the schedule registry is control-plane metadata; each
enqueued run re-resolves and enforces its own tenant scope (see ``PipelineExecutor``).

CRUD is tenant-scoped: a schedule (or its target pipeline) from another tenant is 404.
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Sequence
from datetime import datetime

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.pipeline import Pipeline, PipelineRun
from app.models.schedule import Schedule
from app.reporting import cron
from app.schemas.schedule import ScheduleCreate, ScheduleUpdate
from app.tenancy.context import TenantContext

logger = logging.getLogger(__name__)

EnqueueFn = Callable[[str], None]


def select_due(schedules: Sequence[Schedule], when: datetime) -> list[Schedule]:
    """Return the enabled schedules whose cron is due at ``when`` (minute resolution)."""
    due: list[Schedule] = []
    for schedule in schedules:
        if not schedule.enabled:
            continue
        try:
            if cron.matches(schedule.cron, when):
                due.append(schedule)
        except cron.CronError:
            # A stored cron is validated on write; tolerate a bad one rather than
            # failing the whole heartbeat (skip + log).
            logger.warning(
                "Schedule %s has an invalid cron %r — skipping", schedule.id, schedule.cron
            )
    return due


class ScheduleService:
    """Manage a tenant's schedules and dispatch due pipeline runs."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Tenant-scoped CRUD
    # ------------------------------------------------------------------

    async def list_for_tenant(self, ctx: TenantContext) -> list[Schedule]:
        result = await self._db.execute(
            select(Schedule)
            .where(Schedule.tenant_id == uuid.UUID(ctx.tenant_id))
            .order_by(Schedule.name.asc())
        )
        return list(result.scalars().all())

    async def get_for_tenant(self, ctx: TenantContext, schedule_id: uuid.UUID) -> Schedule:
        result = await self._db.execute(
            select(Schedule).where(
                Schedule.id == schedule_id,
                Schedule.tenant_id == uuid.UUID(ctx.tenant_id),
            )
        )
        schedule = result.scalar_one_or_none()
        if schedule is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
        return schedule

    async def create(self, ctx: TenantContext, data: ScheduleCreate) -> Schedule:
        await self._require_target(ctx, data.target_id)
        schedule = Schedule(
            tenant_id=uuid.UUID(ctx.tenant_id),
            name=data.name,
            target_kind=data.target_kind,
            target_id=data.target_id,
            cron=data.cron,
            enabled=data.enabled,
        )
        self._db.add(schedule)
        await self._db.flush()
        await self._db.refresh(schedule)
        return schedule

    async def update(
        self, ctx: TenantContext, schedule_id: uuid.UUID, data: ScheduleUpdate
    ) -> Schedule:
        schedule = await self.get_for_tenant(ctx, schedule_id)
        if data.name is not None:
            schedule.name = data.name
        if data.cron is not None:
            schedule.cron = data.cron
        if data.enabled is not None:
            schedule.enabled = data.enabled
        await self._db.flush()
        await self._db.refresh(schedule)
        return schedule

    async def delete(self, ctx: TenantContext, schedule_id: uuid.UUID) -> None:
        schedule = await self.get_for_tenant(ctx, schedule_id)
        await self._db.delete(schedule)
        await self._db.flush()

    # ------------------------------------------------------------------
    # Control-plane dispatch (periodiq heartbeat)
    # ------------------------------------------------------------------

    async def create_due_runs(self, now: datetime, enqueue: EnqueueFn) -> list[uuid.UUID]:
        """Create + enqueue a queued run for every pipeline schedule due at ``now``.

        Control-plane (all tenants). Skips schedules whose target pipeline is missing
        or disabled. Returns the created run ids.
        """
        result = await self._db.execute(
            select(Schedule).where(
                Schedule.enabled.is_(True),
                Schedule.target_kind == "pipeline",
            )
        )
        schedules = list(result.scalars().all())

        run_ids: list[uuid.UUID] = []
        for schedule in select_due(schedules, now):
            pipeline = await self._db.get(Pipeline, schedule.target_id)
            if pipeline is None or not pipeline.enabled:
                continue
            run = PipelineRun(
                tenant_id=schedule.tenant_id,
                pipeline_id=pipeline.id,
                status="queued",
            )
            self._db.add(run)
            await self._db.flush()
            await self._db.refresh(run)
            enqueue(str(run.id))
            run_ids.append(run.id)
        return run_ids

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _require_target(self, ctx: TenantContext, pipeline_id: uuid.UUID) -> None:
        result = await self._db.execute(
            select(Pipeline.id).where(
                Pipeline.id == pipeline_id,
                Pipeline.tenant_id == uuid.UUID(ctx.tenant_id),
            )
        )
        if result.first() is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline not found")


def get_schedule_service(
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> ScheduleService:
    """FastAPI dependency: assemble a ``ScheduleService`` from request scope."""
    return ScheduleService(db=db)
