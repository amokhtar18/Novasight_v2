"""Read the backend's definition registry so the code location is generic.

The Dagster code location must run *any* tenant's pipelines and transform jobs and
schedule them from the same rows the API writes — without a per-definition Dagster
object or a redeploy. It therefore reads the backend's control-plane Postgres
directly (it cannot import ``backend/app``, which is a separate deployable).

Golden rule 1: the connection comes entirely from the SAME ``POSTGRES__*`` env the
backend uses, so all layers share one source of truth and nothing is hardcoded.
Golden rule 2: every row carries its tenant's slug (joined here at the boundary) so
the generic jobs scope work to the right tenant; a row's tenant is never inferred
later or trusted from elsewhere.

This module is import-safe without a database driver: the sync driver
(``psycopg``) is only needed when ``load_*`` actually connects, which happens in the
running stack. The pure row→schedule mapping lives in ``dynamic.py`` and is unit
tested with fixture rows.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Engine, create_engine, text


class PostgresSettings(BaseSettings):
    """Control-plane Postgres — identical ``POSTGRES__*`` env the backend uses."""

    model_config = SettingsConfigDict(env_prefix="POSTGRES__", extra="ignore")

    host: str
    port: int = 5432
    user: str
    password: SecretStr
    db: str

    @property
    def url(self) -> str:
        # Sync driver here (Dagster reads synchronously); the backend uses asyncpg.
        return (
            f"postgresql+psycopg://{self.user}:{self.password.get_secret_value()}"
            f"@{self.host}:{self.port}/{self.db}"
        )


# ---------------------------------------------------------------------------
# Row shapes — the slice of each registry table the code location needs.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScheduleRow:
    """One enabled-or-disabled cron binding, with its tenant slug resolved."""

    schedule_id: str
    tenant: str          # tenant slug — what the run-config contract expects
    target_kind: str     # "pipeline" | "transform_job"
    target_id: str
    cron: str
    enabled: bool


@dataclass(frozen=True)
class PipelineRow:
    """The slice of a ``pipelines`` row a generic run needs."""

    pipeline_id: str
    tenant: str
    name: str
    target_table: str


@dataclass(frozen=True)
class TransformRow:
    """The slice of a ``transform_jobs`` row a generic run needs."""

    transform_job_id: str
    tenant: str
    name: str
    selection: str       # dbt selector string ("" == whole project)


def schedule_name(schedule_id: str | uuid.UUID) -> str:
    """Deterministic Dagster schedule name for a registry schedule id.

    Dagster names must match ``[A-Za-z0-9_]+`` (no hyphens), so the UUID hex is used.
    The backend derives the same name to toggle the schedule via GraphQL, so the two
    sides agree without sharing code.
    """
    raw = schedule_id.hex if isinstance(schedule_id, uuid.UUID) else uuid.UUID(str(schedule_id)).hex
    return f"sched_{raw}"


# ---------------------------------------------------------------------------
# Loaders — synchronous reads against the control-plane database (stack only).
# ---------------------------------------------------------------------------


@lru_cache
def _engine() -> Engine:
    """Process-wide sync engine, built once from ``POSTGRES__*`` env."""
    settings = PostgresSettings()  # type: ignore[call-arg]  # values come from env
    # pool_pre_ping: the schedule read may run after a long idle in the daemon.
    return create_engine(settings.url, pool_pre_ping=True)


def load_schedule_rows(engine: Engine | None = None) -> list[ScheduleRow]:
    """Load every schedule with its tenant slug, for building Dagster schedules."""
    eng = engine or _engine()
    query = text(
        "SELECT s.id, s.target_kind, s.target_id, s.cron, s.enabled, t.slug "
        "FROM schedules s JOIN tenants t ON t.id = s.tenant_id"
    )
    with eng.connect() as conn:
        rows = conn.execute(query).all()
    return [
        ScheduleRow(
            schedule_id=str(r[0]),
            target_kind=str(r[1]),
            target_id=str(r[2]),
            cron=str(r[3]),
            enabled=bool(r[4]),
            tenant=str(r[5]),
        )
        for r in rows
    ]


def load_pipeline(pipeline_id: str, engine: Engine | None = None) -> PipelineRow:
    """Resolve a pipeline by id (with its tenant slug). Raises if not found."""
    eng = engine or _engine()
    query = text(
        "SELECT p.id, p.name, p.target_table, t.slug "
        "FROM pipelines p JOIN tenants t ON t.id = p.tenant_id "
        "WHERE p.id = :pid"
    )
    with eng.connect() as conn:
        row = conn.execute(query, {"pid": pipeline_id}).first()
    if row is None:
        raise LookupError(f"pipeline {pipeline_id} not found")
    return PipelineRow(
        pipeline_id=str(row[0]), name=str(row[1]), target_table=str(row[2]), tenant=str(row[3])
    )


def load_transform(transform_job_id: str, engine: Engine | None = None) -> TransformRow:
    """Resolve a transform job by id (with its tenant slug). Raises if not found."""
    eng = engine or _engine()
    query = text(
        "SELECT j.id, j.name, j.selection, t.slug "
        "FROM transform_jobs j JOIN tenants t ON t.id = j.tenant_id "
        "WHERE j.id = :jid"
    )
    with eng.connect() as conn:
        row = conn.execute(query, {"jid": transform_job_id}).first()
    if row is None:
        raise LookupError(f"transform job {transform_job_id} not found")
    return TransformRow(
        transform_job_id=str(row[0]), name=str(row[1]), selection=str(row[2]), tenant=str(row[3])
    )
