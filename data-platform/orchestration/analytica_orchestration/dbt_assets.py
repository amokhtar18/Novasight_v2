"""dbt models as Dagster assets, with tests as the blocking quality gate.

``@dbt_assets`` loads every model from the manifest into the asset graph. Running
``dbt build`` (not ``run``) means dbt's tests execute in DAG order and are surfaced as
Dagster **asset checks** — the quality gate from the dbt-dagster-workflow skill:

* **Blocking.** ``dbt build`` runs each model, then its tests, before any downstream
  model. When a test fails, dbt skips everything downstream — so a failing *upstream*
  check (e.g. a staging test) means the mart is never built. No mart ``Output`` is
  yielded, the gate held, and the asset run fails (``dbt`` exits non-zero, which
  ``stream`` raises once the events are drained).
* **Observable.** Each failing check is turned into a structured ``QualityGateFailure``
  event and emitted on the alerting seam (see ``quality_events``) before the run fails,
  so the reporting/alerting layer can consume it later.

Lineage: the dbt ``phase1.regional_sales`` source maps to the asset key
``["phase1", "regional_sales"]``, which the dlt ingestion asset (``ingestion.py``)
publishes — so raw -> staging -> intermediate -> mart connects automatically.
"""
from collections.abc import Iterable, Iterator
from typing import Any

from dagster import AssetCheckResult, AssetExecutionContext
from dagster_dbt import DbtCliResource, dbt_assets

from .dbt_resource import dbt_project
from .quality_events import (
    SupportsError,
    build_failure_event,
    emit_quality_gate_failure,
)
from .settings import get_settings


def _gate_stream(
    events: Iterable[Any], *, tenant: str, log: SupportsError
) -> Iterator[Any]:
    """Forward dbt events unchanged, emitting an alert for each failing asset check.

    Kept separate from the asset body so it is unit-testable without dbt or a live
    warehouse: feed it a simulated event stream and a fake logger. It never alters the
    stream — a mart that dbt skipped stays skipped — it only *observes* failed checks.
    """
    for event in events:
        if isinstance(event, AssetCheckResult) and not event.passed:
            emit_quality_gate_failure(log, build_failure_event(event, tenant=tenant))
        yield event


@dbt_assets(manifest=dbt_project.manifest_path)
def analytica_dbt_assets(
    context: AssetExecutionContext, dbt: DbtCliResource
) -> Iterator[Any]:
    """Materialize the dbt models and run their tests as the blocking quality gate.

    ``dbt build`` runs models and tests together in DAG order, so each model's quality
    gate runs immediately after it is built and before anything downstream of it.
    """
    # Tenant resolved at the boundary (golden rule 2): the dbt schema == the tenant's
    # ClickHouse database. Stamped onto every quality-gate event so alerts are scoped.
    tenant = get_settings().dbt_schema
    yield from _gate_stream(
        dbt.cli(["build"], context=context).stream(),
        tenant=tenant,
        log=context.log,
    )
