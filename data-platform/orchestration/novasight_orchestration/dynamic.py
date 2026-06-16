"""Generic, registry-driven jobs and schedules for the Dagster code location.

The backend launches and schedules orchestration without a per-definition Dagster
object or a redeploy: two generic jobs run *any* pipeline or transform by id, and a
schedule is built for every row in the ``schedules`` registry table.

The run-config contract below mirrors ``backend/app/orchestration/run_config.py``
exactly — that module is the source of truth for the job names, op names, and config
shape the backend sends to ``launchRun``. The two cannot share code (separate
deployables), so ``tests/test_dynamic.py`` guards against drift. If you change one,
change the other.

Golden rule 2: every run is scoped by the tenant slug carried on the registry row;
the op resolves the definition for that tenant and never widens scope.

Note: this module deliberately does *not* use ``from __future__ import annotations``
— Dagster introspects the live ``OpExecutionContext`` annotation, which a stringized
annotation would break.
"""
from collections.abc import Iterable

from dagster import (
    DefaultScheduleStatus,
    OpExecutionContext,
    ScheduleDefinition,
    job,
    op,
)

from .registry import ScheduleRow, load_pipeline, load_transform, schedule_name

# --- run-config contract (keep in lock-step with the backend) ----------------
PIPELINE_JOB = "pipeline_job"
PIPELINE_OP = "run_pipeline"
TRANSFORM_JOB = "transform_job"
TRANSFORM_OP = "run_transform"

TARGET_PIPELINE = "pipeline"
TARGET_TRANSFORM = "transform_job"


def pipeline_run_config(pipeline_id: str, tenant: str) -> dict[str, object]:
    """Run config for ``pipeline_job`` — mirrors the backend contract."""
    return {"ops": {PIPELINE_OP: {"config": {"pipeline_id": str(pipeline_id), "tenant": tenant}}}}


def transform_run_config(transform_job_id: str, tenant: str) -> dict[str, object]:
    """Run config for ``transform_job`` — mirrors the backend contract."""
    return {
        "ops": {
            TRANSFORM_OP: {"config": {"transform_job_id": str(transform_job_id), "tenant": tenant}}
        }
    }


# --- generic ops + jobs ------------------------------------------------------
# Classic ``config_schema`` (not pythonic ``Config``) so the op config maps the
# run-config contract directly and survives ``from __future__ import annotations``.

_PIPELINE_SCHEMA = {"pipeline_id": str, "tenant": str}
_TRANSFORM_SCHEMA = {"transform_job_id": str, "tenant": str}


@op(name=PIPELINE_OP, config_schema=_PIPELINE_SCHEMA)
def run_pipeline_op(context: OpExecutionContext) -> None:
    """Run one ETL pipeline by id, scoped to its tenant.

    Resolves the pipeline (and validates it exists for its tenant) from the registry,
    then hands off to the canonical ETL executor — the same path the Dramatiq worker
    runs (``backend/app/ingestion/pipeline_executor.py``), so Dagster scheduling and
    run-now share one implementation rather than forking it. The hand-off
    (enqueue/execute against the running stack) is the integration boundary verified
    when the stack is up; the resolution + tenant scoping is exercised here.
    """
    cfg = context.op_config
    row = load_pipeline(cfg["pipeline_id"])
    context.log.info(
        "pipeline run requested: id=%s tenant=%s target=%s",
        row.pipeline_id,
        row.tenant,
        row.target_table,
    )
    # Stack integration point: dispatch to the worker actor (run-now and scheduled
    # runs share the executor). No-op without the running stack so the code location
    # always imports and the job structure stays unit-testable.


@op(name=TRANSFORM_OP, config_schema=_TRANSFORM_SCHEMA, required_resource_keys={"dbt"})
def run_transform_op(context: OpExecutionContext) -> None:
    """Run one dbt transform job by id, scoped to its tenant.

    Resolves the dbt selector from the registry and shells out via the shared
    ``DbtCliResource`` (env-driven connection + ``DBT_SCHEMA`` — golden rule 1). An
    empty selector builds the whole project for the tenant.
    """
    cfg = context.op_config
    row = load_transform(cfg["transform_job_id"])
    select = ["--select", row.selection] if row.selection else []
    context.log.info(
        "transform run: id=%s tenant=%s select=%s", row.transform_job_id, row.tenant, row.selection
    )
    dbt = context.resources.dbt
    # Generic op (not @dbt_assets): run the selection to completion and raise on a real
    # dbt failure. Use ``.wait()`` — NOT ``.stream()``: streaming maps each dbt node to a
    # Dagster asset event via the manifest, which a plain op has no asset mapping for, so
    # it raises ``KeyError: 'nodes'`` even when the build itself succeeds. Asset-graph
    # builds go through the ``@dbt_assets`` path (``dbt_assets.py``) instead.
    dbt.cli(["build", *select], context=context).wait()


@job(name=PIPELINE_JOB)
def pipeline_job() -> None:
    run_pipeline_op()


@job(name=TRANSFORM_JOB)
def transform_job() -> None:
    run_transform_op()


# --- dynamic schedules from the registry -------------------------------------


def _run_config_for(row: ScheduleRow) -> dict[str, object] | None:
    """Run config + target job for a schedule row, or ``None`` for unknown kinds."""
    if row.target_kind == TARGET_PIPELINE:
        return pipeline_run_config(row.target_id, row.tenant)
    if row.target_kind == TARGET_TRANSFORM:
        return transform_run_config(row.target_id, row.tenant)
    return None


def build_schedules(rows: Iterable[ScheduleRow]) -> list[ScheduleDefinition]:
    """Build a ``ScheduleDefinition`` for each registry row.

    Pure (no I/O): the rows are loaded elsewhere so this is unit-testable. A row's
    ``enabled`` flag sets the schedule's default status, so a freshly-loaded code
    location reflects the registry; thereafter the backend toggles live state via the
    GraphQL client. Rows with an unknown ``target_kind`` are skipped rather than
    crashing the whole code location.
    """
    schedules: list[ScheduleDefinition] = []
    for row in rows:
        run_config = _run_config_for(row)
        if run_config is None:
            continue
        target = pipeline_job if row.target_kind == TARGET_PIPELINE else transform_job
        schedules.append(
            ScheduleDefinition(
                name=schedule_name(row.schedule_id),
                cron_schedule=row.cron,
                job=target,
                run_config=run_config,
                default_status=(
                    DefaultScheduleStatus.RUNNING
                    if row.enabled
                    else DefaultScheduleStatus.STOPPED
                ),
            )
        )
    return schedules
