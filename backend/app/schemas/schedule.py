"""Schemas for pipeline schedules (#4).

A schedule binds a cron expression to a target (a pipeline) so it runs on a cadence
without anyone clicking *Run*. The periodiq dispatcher enqueues due runs through the
same worker path as run-now (see ``app.ingestion.scheduler``).

The cron is validated at the boundary against the project's 5-field matcher, so a
malformed expression is a 422 before anything is stored. ``target_kind`` is currently
``pipeline`` only (scheduling dbt transforms arrives with the dbt run path, #7).
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.reporting import cron

TargetKind = Literal["pipeline"]


def _validate_cron(value: str) -> str:
    try:
        cron.matches(value, datetime.now(tz=UTC))
    except cron.CronError as exc:
        raise ValueError(f"invalid cron expression: {exc}") from exc
    return value


class ScheduleCreate(BaseModel):
    """Body for ``POST /schedules``."""

    name: str = Field(..., min_length=1, max_length=255)
    target_kind: TargetKind = "pipeline"
    target_id: uuid.UUID
    cron: str = Field(..., min_length=1, max_length=128)
    enabled: bool = True

    _check_cron = field_validator("cron")(_validate_cron)


class ScheduleUpdate(BaseModel):
    """Body for ``PATCH /schedules/{id}`` — partial."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    cron: str | None = Field(default=None, min_length=1, max_length=128)
    enabled: bool | None = None

    @field_validator("cron")
    @classmethod
    def _check_cron(cls, value: str | None) -> str | None:
        return None if value is None else _validate_cron(value)


class ScheduleRead(BaseModel):
    """A schedule as returned to clients."""

    id: uuid.UUID
    name: str
    target_kind: str
    target_id: uuid.UUID
    cron: str
    enabled: bool
    created_at: datetime
    updated_at: datetime
