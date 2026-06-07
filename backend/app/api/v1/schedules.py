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


def _to_read(s: Schedule) -> ScheduleRead:
    return ScheduleRead(
        id=s.id,
        name=s.name,
        target_kind=s.target_kind,
        target_id=s.target_id,
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
    """List the tenant's schedules."""
    return [_to_read(s) for s in await svc.list_for_tenant(ctx)]


@router.get("/{schedule_id}", response_model=ScheduleRead)
async def get_schedule(
    schedule_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    svc: ScheduleService = Depends(get_schedule_service),  # noqa: B008
) -> ScheduleRead:
    """Fetch one schedule (404 if not in the caller's tenant)."""
    return _to_read(await svc.get_for_tenant(ctx, schedule_id))


@router.post("", response_model=ScheduleRead, status_code=status.HTTP_201_CREATED)
async def create_schedule(
    payload: ScheduleCreate,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    _: Principal = Depends(require_tenant_superuser),  # noqa: B008
    svc: ScheduleService = Depends(get_schedule_service),  # noqa: B008
) -> ScheduleRead:
    """Create a schedule for a pipeline (target must belong to the tenant)."""
    return _to_read(await svc.create(ctx, payload))


@router.patch("/{schedule_id}", response_model=ScheduleRead)
async def update_schedule(
    schedule_id: uuid.UUID,
    payload: ScheduleUpdate,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    _: Principal = Depends(require_tenant_superuser),  # noqa: B008
    svc: ScheduleService = Depends(get_schedule_service),  # noqa: B008
) -> ScheduleRead:
    """Update a schedule (partial; cron re-validated)."""
    return _to_read(await svc.update(ctx, schedule_id, payload))


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
