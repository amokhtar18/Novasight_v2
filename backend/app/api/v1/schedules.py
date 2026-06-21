"""Schedule endpoints — cron schedules for pipelines (#4).

Reads need only a tenant context. Mutations require the tenant **superuser** role
(scheduling drives the data plane). The cron is validated at the schema boundary; the
target pipeline must belong to the caller's tenant. The dispatcher
(``app.ingestion.scheduler``) runs due schedules via the worker — no Dagster needed.
The tenant is resolved from the JWT, never a body/path value.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response, status

from app.core.security import Principal, require_tenant_superuser
from app.models.schedule import Schedule
from app.schemas.schedule import ScheduleCreate, ScheduleRead, ScheduleUpdate
from app.services.schedules import ScheduleService, get_schedule_service
from app.tenancy.context import TenantContext, get_tenant_context

router = APIRouter(prefix="/schedules", tags=["schedules"])


def _to_read(s: Schedule, pipeline_ids: list[uuid.UUID]) -> ScheduleRead:
    return ScheduleRead(
        id=s.id,
        name=s.name,
        target_kind=s.target_kind,
        pipeline_ids=pipeline_ids,
        cron=s.cron,
        enabled=s.enabled,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


@router.get("", response_model=list[ScheduleRead])
async def list_schedules(
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    svc: ScheduleService = Depends(get_schedule_service),  # noqa: B008
) -> list[ScheduleRead]:
    """List the tenant's schedules with their attached pipelines."""
    schedules = await svc.list_for_tenant(ctx)
    pmap = await svc.pipeline_id_map(ctx)
    return [_to_read(s, pmap.get(s.id, [])) for s in schedules]


@router.get("/{schedule_id}", response_model=ScheduleRead)
async def get_schedule(
    schedule_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    svc: ScheduleService = Depends(get_schedule_service),  # noqa: B008
) -> ScheduleRead:
    """Fetch one schedule (404 if not in the caller's tenant)."""
    schedule = await svc.get_for_tenant(ctx, schedule_id)
    return _to_read(schedule, await svc.pipeline_ids_for(ctx, schedule.id))


@router.post("", response_model=ScheduleRead, status_code=status.HTTP_201_CREATED)
async def create_schedule(
    payload: ScheduleCreate,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    _: Principal = Depends(require_tenant_superuser),  # noqa: B008
    svc: ScheduleService = Depends(get_schedule_service),  # noqa: B008
) -> ScheduleRead:
    """Create a reusable schedule across one or more of the tenant's pipelines."""
    schedule = await svc.create(ctx, payload)
    return _to_read(schedule, await svc.pipeline_ids_for(ctx, schedule.id))


@router.patch("/{schedule_id}", response_model=ScheduleRead)
async def update_schedule(
    schedule_id: uuid.UUID,
    payload: ScheduleUpdate,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    _: Principal = Depends(require_tenant_superuser),  # noqa: B008
    svc: ScheduleService = Depends(get_schedule_service),  # noqa: B008
) -> ScheduleRead:
    """Update a schedule (partial; cron re-validated, attachments replaced if given)."""
    schedule = await svc.update(ctx, schedule_id, payload)
    return _to_read(schedule, await svc.pipeline_ids_for(ctx, schedule.id))


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(
    schedule_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    _: Principal = Depends(require_tenant_superuser),  # noqa: B008
    svc: ScheduleService = Depends(get_schedule_service),  # noqa: B008
) -> Response:
    """Delete a schedule."""
    await svc.delete(ctx, schedule_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
