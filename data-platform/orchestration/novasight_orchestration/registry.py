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


@dataclass(frozen=True)
class TenantRow:
    """A tenant and the data surfaces a catalog run scopes itself to.

    ``clickhouse_db`` / ``iceberg_namespace`` come from the tenant's resource map —
    the same per-tenant isolation the rest of the platform resolves at the boundary
    (golden rule 2). The catalog asset filters its ingestion to exactly these.
    """

    tenant: str              # tenant slug — what the run-config contract expects
    clickhouse_db: str       # tenant's ClickHouse database (== dbt schema)
    iceberg_namespace: str   # tenant's Iceberg namespace (lake landing zone)


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


# A tenant only enters the catalog once it has a resource map (its ClickHouse DB /
# Iceberg namespace exist), so every loader here INNER JOINs ``tenant_resource_maps``.
_TENANT_SCOPE_SELECT = (
    "SELECT t.slug, m.clickhouse_db, m.iceberg_namespace "
    "FROM tenants t JOIN tenant_resource_maps m ON m.tenant_id = t.id"
)


def _tenant_row(row: object) -> TenantRow:
    return TenantRow(
        tenant=str(row[0]), clickhouse_db=str(row[1]), iceberg_namespace=str(row[2])  # type: ignore[index]
    )


def load_tenants(engine: Engine | None = None) -> list[TenantRow]:
    """Load every provisioned tenant's catalog scope, for the per-tenant schedules.

    Only tenants with a resource map are returned (the INNER JOIN), so a half-created
    tenant never gets a catalog run pointed at a database that does not exist yet.
    """
    eng = engine or _engine()
    with eng.connect() as conn:
        rows = conn.execute(text(_TENANT_SCOPE_SELECT)).all()
    return [_tenant_row(r) for r in rows]


def load_tenant(slug: str, engine: Engine | None = None) -> TenantRow:
    """Resolve one tenant's catalog scope by slug. Raises if not found / unprovisioned."""
    eng = engine or _engine()
    with eng.connect() as conn:
        row = conn.execute(text(f"{_TENANT_SCOPE_SELECT} WHERE t.slug = :slug"), {"slug": slug}).first()
    if row is None:
        raise LookupError(f"tenant {slug} not found or has no resource map")
    return _tenant_row(row)


# ---------------------------------------------------------------------------
# Lineage inputs — the per-tenant rows the cross-system lineage stage maps into
# OpenMetadata edges (catalog_lineage.py). Read-only metadata; no source secrets.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CatalogPipelineRow:
    """A pipeline's source→target shape, for source→raw→serving lineage edges."""

    name: str
    target_table: str        # landing table name (Iceberg namespace + ClickHouse DB)
    source_kind: str         # connector kind, e.g. "sql_database" | "filesystem"
    source_name: str         # the source connection's display name
    source_object: str       # the extracted object (source table / file)
    source_schema: str       # the source schema ("" when not applicable, e.g. files)


@dataclass(frozen=True)
class CatalogSemanticRow:
    """A semantic model's cube→base-table shape, for ClickHouse→Cube lineage edges."""

    name: str                # cube name (the logical semantic entity)
    base_table: str          # ClickHouse serving table the cube is built over


def load_pipelines_for_tenant(slug: str, engine: Engine | None = None) -> list[CatalogPipelineRow]:
    """Load a tenant's pipelines with the source shape lineage needs (no secrets)."""
    eng = engine or _engine()
    query = text(
        "SELECT p.name, p.target_table, p.config, sc.kind, sc.name "
        "FROM pipelines p "
        "JOIN source_connections sc ON sc.id = p.source_connection_id "
        "JOIN tenants t ON t.id = p.tenant_id "
        "WHERE t.slug = :slug"
    )
    with eng.connect() as conn:
        rows = conn.execute(query, {"slug": slug}).all()
    result: list[CatalogPipelineRow] = []
    for r in rows:
        cfg = r[2] if isinstance(r[2], dict) else {}
        result.append(
            CatalogPipelineRow(
                name=str(r[0]),
                target_table=str(r[1]),
                source_kind=str(r[3]),
                source_name=str(r[4]),
                source_object=str(cfg.get("object", "")),
                source_schema=str(cfg.get("source_schema") or ""),
            )
        )
    return result


def load_semantic_models_for_tenant(slug: str, engine: Engine | None = None) -> list[CatalogSemanticRow]:
    """Load a tenant's semantic models (cube name + base table) for lineage edges."""
    eng = engine or _engine()
    query = text(
        "SELECT s.name, s.base_table "
        "FROM semantic_models s JOIN tenants t ON t.id = s.tenant_id "
        "WHERE t.slug = :slug AND s.enabled = true"
    )
    with eng.connect() as conn:
        rows = conn.execute(query, {"slug": slug}).all()
    return [CatalogSemanticRow(name=str(r[0]), base_table=str(r[1])) for r in rows]
