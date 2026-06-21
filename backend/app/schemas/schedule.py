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
    """Body for ``POST /schedules``.

    A reusable schedule attaches to one *or more* pipelines (#3): ``pipeline_ids``
    must be non-empty and every id must belong to the caller's tenant (enforced in
    the service). ``target_kind`` stays ``pipeline``.
    """

    name: str = Field(..., min_length=1, max_length=255)
    target_kind: TargetKind = "pipeline"
    pipeline_ids: list[uuid.UUID] = Field(..., min_length=1, max_length=100)
    cron: str = Field(..., min_length=1, max_length=128)
    enabled: bool = True

    _check_cron = field_validator("cron")(_validate_cron)


class ScheduleUpdate(BaseModel):
    """Body for ``PATCH /schedules/{id}`` — partial.

    When ``pipeline_ids`` is provided it *replaces* the schedule's attachments (must
    be non-empty). Omit it to leave attachments unchanged.
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    cron: str | None = Field(default=None, min_length=1, max_length=128)
    enabled: bool | None = None
    pipeline_ids: list[uuid.UUID] | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("cron")
    @classmethod
    def _check_cron(cls, value: str | None) -> str | None:
        return None if value is None else _validate_cron(value)


class ScheduleRead(BaseModel):
    """A schedule as returned to clients (with its attached pipelines)."""

    id: uuid.UUID
    name: str
    target_kind: str
    pipeline_ids: list[uuid.UUID]
    cron: str
    enabled: bool
    created_at: datetime
    updated_at: datetime
