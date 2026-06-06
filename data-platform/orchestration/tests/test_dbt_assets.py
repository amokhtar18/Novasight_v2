"""Tests for the quality-gate stream wrapper (``dbt_assets._gate_stream``).

These exercise the gate's contract without a live warehouse by feeding ``_gate_stream``
a *simulated* ``dbt build`` event stream — exactly the objects dagster-dbt yields:
``Output`` per built model and ``AssetCheckResult`` per test. The simulation mirrors
dbt's real DAG-order behavior:

* good run  -> staging Output, passing checks, mart Output, passing mart check.
* bad row   -> staging Output, FAILING staging check, then dbt stops and ``stream``
               raises (non-zero exit). The mart Output is **never yielded** — the gate
               blocked it.

So the wrapper itself is what we assert: it emits a structured alert for the failing
check and forwards the stream untouched (it cannot resurrect a mart dbt skipped).
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from dagster import AssetCheckResult, AssetCheckSeverity, AssetKey, Output

from novasight_orchestration.dbt_assets import _gate_stream

TENANT = "tenant_local"
STAGING = AssetKey(["stg_phase1__regional_sales"])
MART = AssetKey(["mart_regional_sales"])


class _FakeLog:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)


class _DbtBuildFailed(Exception):
    """Stand-in for dagster-dbt's runtime error raised after a failed ``dbt build``."""


def _check(asset_key: AssetKey, name: str, *, passed: bool) -> AssetCheckResult:
    return AssetCheckResult(
        passed=passed,
        asset_key=asset_key,
        check_name=name,
        severity=AssetCheckSeverity.ERROR,
        metadata={"dagster_dbt/failed_row_count": 0 if passed else 1, "status": "pass" if passed else "fail"},
    )


def _good_run() -> Iterator[Any]:
    yield Output(value=None, output_name="stg_phase1__regional_sales")
    yield _check(STAGING, "not_null_region", passed=True)
    yield _check(STAGING, "unique_region", passed=True)
    yield Output(value=None, output_name="mart_regional_sales")
    yield _check(MART, "expect_amount_between", passed=True)


def _bad_row_run() -> Iterator[Any]:
    # Staging builds, then its unique check fails on the duplicate region. dbt stops:
    # the intermediate + mart are skipped (no Output), and the CLI exits non-zero,
    # which dagster-dbt surfaces by raising once the events are drained.
    yield Output(value=None, output_name="stg_phase1__regional_sales")
    yield _check(STAGING, "not_null_region", passed=True)
    yield _check(STAGING, "unique_region", passed=False)
    raise _DbtBuildFailed("dbt build failed: 1 test failure (unique_region)")


def _drain(events: Iterator[Any], log: _FakeLog) -> list[Any]:
    return list(_gate_stream(events, tenant=TENANT, log=log))


def test_good_run_passes_and_emits_no_alert() -> None:
    log = _FakeLog()

    forwarded = _drain(_good_run(), log)

    assert log.errors == []
    # The mart materialized: its Output is forwarded to Dagster.
    mart_outputs = [
        e for e in forwarded
        if isinstance(e, Output) and e.output_name == "mart_regional_sales"
    ]
    assert len(mart_outputs) == 1


def test_bad_row_fails_gate_blocks_mart_and_emits_alert() -> None:
    log = _FakeLog()
    forwarded: list[Any] = []

    raised = False
    try:
        for event in _gate_stream(_bad_row_run(), tenant=TENANT, log=log):
            forwarded.append(event)
    except _DbtBuildFailed:
        raised = True

    # The run fails (gate is blocking, not a warning).
    assert raised
    # The mart never materialized — no mart Output ever crossed the gate.
    assert not any(
        isinstance(e, Output) and e.output_name == "mart_regional_sales"
        for e in forwarded
    )
    # Exactly one structured alert was emitted, for the failing staging check.
    assert len(log.errors) == 1
    payload = json.loads(log.errors[0])
    assert payload["event_type"] == "quality_gate_failure"
    assert payload["tenant"] == TENANT
    assert payload["asset_key"] == "stg_phase1__regional_sales"
    assert payload["check_name"] == "unique_region"
    assert payload["severity"] == "ERROR"


def test_passing_checks_never_alert() -> None:
    log = _FakeLog()

    _drain(iter([_check(STAGING, "not_null_region", passed=True)]), log)

    assert log.errors == []
