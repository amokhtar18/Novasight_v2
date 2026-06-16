"""Pipeline execution — extract → Iceberg → ClickHouse, with run lifecycle (#3).

The executor runs off the request path (a Dramatiq worker, see ``actors.py``). Its
*orchestration* — load the run, re-resolve the tenant scope from the registry, walk
queued→running→success|error, and record rows/timings/error — is the load-bearing,
fully unit-tested part. The three infra steps (extract from the source, write the
landing table to Iceberg, register it in ClickHouse) are **injected**, so tests
exercise every lifecycle path with fakes and no live infra.

``build_pipeline_executor`` wires the real steps (connector extraction,
``iceberg_writer``, ``ClickHouseDatasetService.register_table``); those adapters are
thin and verified against the running stack.

Tenancy (golden rule 2): the worker re-derives the ``TenantContext`` from the
pipeline's tenant via ``resolve_tenant_context_for_job`` — never from the work item.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.connectors.base import ColumnSelect, ExtractSpec, FilterSpec
from app.models.pipeline import Pipeline, PipelineRun
from app.models.source_connection import SourceConnection
from app.models.tenant import Tenant
from app.schemas.pipeline import PipelineConfig
from app.tenancy.context import TenantContext
from app.tenancy.job_context import resolve_tenant_context_for_job

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoadPlan:
    """How the load step lands the extracted batch (disposition + upsert key)."""

    disposition: str = "overwrite"
    primary_key: list[str] = field(default_factory=list)


# Injected step signatures. ``extract`` receives the selected object + the read-shape
# spec (columns/filters/CDC); ``load`` receives the write plan (disposition + key).
ExtractStep = Callable[
    [TenantContext, SourceConnection, dict[str, Any] | None, str, ExtractSpec], Awaitable[Any]
]
LoadStep = Callable[[TenantContext, str, Any, LoadPlan], int]
RegisterStep = Callable[[TenantContext, str], str]
DecryptStep = Callable[[str | None], dict[str, Any] | None]

# Cap the stored error so a verbose driver traceback can't bloat the run row.
_MAX_ERROR_LEN = 2000


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _extract_spec(cfg: PipelineConfig, *, cdc_since: object) -> ExtractSpec:
    """Translate a pipeline config + stored watermark into a connector ``ExtractSpec``."""
    columns = [
        ColumnSelect(source_name=c.source_name, target_name=c.target_name)
        for c in cfg.columns
        if c.included
    ]
    filters = [
        FilterSpec(column=f.column, operator=f.operator, value=f.value)
        for f in cfg.source_filters
    ]
    # Incremental only: apply the CDC predicate when there's a column and a prior mark.
    cdc_column = cfg.cdc_column if cfg.write_disposition == "incremental" else None
    return ExtractSpec(
        columns=columns,
        schema=cfg.source_schema,
        filters=filters,
        cdc_column=cdc_column,
        cdc_since=cdc_since if cdc_column else None,
    )


def _cdc_target_name(cfg: PipelineConfig) -> str | None:
    """The CDC column's *target* name (post-rename) — what the Arrow batch is keyed by."""
    if cfg.cdc_column is None:
        return None
    for c in cfg.columns:
        if c.source_name == cfg.cdc_column:
            return c.target_name
    return cfg.cdc_column


def _max_watermark(arrow: Any, column: str | None) -> Any:  # noqa: ANN401 — pyarrow.Table
    """Max value of ``column`` in the batch, JSON-serialised (None if absent/empty)."""
    if column is None or arrow is None:
        return None
    try:
        import pyarrow.compute as pc

        if column not in arrow.column_names or arrow.num_rows == 0:
            return None
        value = pc.max(arrow.column(column)).as_py()  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - defensive; never fail a successful load
        return None
    if value is None:
        return None
    # Datetimes/dates aren't JSON-serialisable; store ISO text (drivers compare it back).
    return value.isoformat() if hasattr(value, "isoformat") else value


class PipelineExecutor:
    """Run a ``PipelineRun`` to completion, recording its lifecycle on the row."""

    def __init__(
        self,
        *,
        extract: ExtractStep,
        load: LoadStep,
        register: RegisterStep,
        decrypt: DecryptStep,
    ) -> None:
        self._extract = extract
        self._load = load
        self._register = register
        self._decrypt = decrypt

    async def execute(self, db: AsyncSession, run_id: uuid.UUID) -> None:
        """Execute the run ``run_id``: extract → load → register, updating status."""
        run = await db.get(PipelineRun, run_id)
        if run is None:
            logger.warning("Pipeline run %s not found — nothing to execute", run_id)
            return
        pipeline = await db.get(Pipeline, run.pipeline_id)
        source = (
            await db.get(SourceConnection, pipeline.source_connection_id)
            if pipeline is not None
            else None
        )
        if pipeline is None or source is None:
            await self._mark_error(db, run, "pipeline or source connection missing")
            return

        run.status = "running"
        run.started_at = _now()
        await db.flush()

        try:
            tenant = await db.get(Tenant, pipeline.tenant_id)
            if tenant is None:
                raise RuntimeError("tenant not found")
            ctx = await resolve_tenant_context_for_job(tenant.slug, db)
            cfg = PipelineConfig.model_validate(pipeline.config)
            if cfg.scd_type == "scd2":
                raise RuntimeError("SCD type 2 (history) is not yet supported")
            secret = self._decrypt(source.secret_ciphertext)

            # Read shape (columns/filters + incremental CDC from the stored cursor) and
            # write plan (disposition + upsert key) both come from the pipeline config.
            cursor = pipeline.cursor or {}
            spec = _extract_spec(cfg, cdc_since=cursor.get("cdc"))
            plan = LoadPlan(
                disposition=cfg.write_disposition, primary_key=list(cfg.primary_key)
            )

            arrow = await self._extract(ctx, source, secret, cfg.object, spec)
            rows = await asyncio.to_thread(self._load, ctx, pipeline.target_table, arrow, plan)
            await asyncio.to_thread(self._register, ctx, pipeline.target_table)

            # Advance the CDC high-water mark so the next incremental run pulls only newer
            # rows. Stored JSON-safe; None when this batch had no rows for the column.
            if cfg.cdc_column:
                new_wm = _max_watermark(arrow, _cdc_target_name(cfg))
                if new_wm is not None:
                    pipeline.cursor = {**cursor, "cdc": new_wm}

            run.status = "success"
            run.rows = int(rows)
            run.error = None
            run.finished_at = _now()
            await db.flush()
            logger.info("Pipeline run %s succeeded (%d rows)", run_id, rows)
        except Exception as exc:
            logger.exception("Pipeline run %s failed", run_id)
            await self._mark_error(db, run, f"{type(exc).__name__}: {exc}")

    @staticmethod
    async def _mark_error(db: AsyncSession, run: PipelineRun, message: str) -> None:
        run.status = "error"
        run.error = message[:_MAX_ERROR_LEN]
        run.finished_at = _now()
        await db.flush()


def build_pipeline_executor() -> PipelineExecutor:
    """Assemble a ``PipelineExecutor`` wired to the real infra adapters.

    Used by the worker actor. The adapters are thin: connector extraction,
    ``iceberg_writer.write_arrow_table``, and ``register_table`` — each reused from
    the existing ingestion/serving code and verified against the running stack.
    """
    from app.core.clickhouse import get_clickhouse_client
    from app.core.config import get_settings
    from app.core.crypto import build_kms_provider, decrypt_value
    from app.core.object_store import get_object_store
    from app.ingestion.connectors import build_connector
    from app.ingestion.iceberg_writer import write_arrow_table
    from app.services.clickhouse_datasets import ClickHouseDatasetService

    settings = get_settings()
    store = get_object_store(settings)

    async def extract(
        ctx: TenantContext,
        source: SourceConnection,
        secret: dict[str, Any] | None,
        target: str,
        spec: ExtractSpec,
    ) -> Any:  # noqa: ANN401 — pyarrow.Table (no stubs)
        connector = build_connector(source.kind, store=store)
        return await connector.extract(source.config, secret, target=target, spec=spec)

    def load(
        ctx: TenantContext, table: str, arrow: Any, plan: LoadPlan  # noqa: ANN401 — pyarrow.Table
    ) -> int:
        return write_arrow_table(
            ctx=ctx,
            settings=settings,
            table_name=table,
            arrow_table=arrow,
            disposition=plan.disposition,
            primary_key=plan.primary_key,
        )

    def register(ctx: TenantContext, table: str) -> str:
        ch = get_clickhouse_client(settings)
        return ClickHouseDatasetService(ch=ch, settings=settings).register_table(ctx, table)

    def decrypt(token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        result: dict[str, Any] = json.loads(decrypt_value(build_kms_provider(settings), token))
        return result

    return PipelineExecutor(extract=extract, load=load, register=register, decrypt=decrypt)
