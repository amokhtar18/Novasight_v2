"""Tests for the generic, registry-driven jobs and schedules (``dynamic.py``).

These exercise the pure mapping from registry rows to Dagster objects without a live
database or a running Dagster — the DB read (``registry.load_*``) is stack-verified.
The run-config contract is asserted explicitly because it must stay in lock-step with
``backend/app/orchestration/run_config.py`` (the two are separate deployables and
cannot share code).
"""
from __future__ import annotations

import pytest
from dagster import DefaultScheduleStatus, build_op_context

import novasight_orchestration.dynamic as dyn
from novasight_orchestration.dynamic import (
    PIPELINE_JOB,
    PIPELINE_OP,
    TRANSFORM_JOB,
    TRANSFORM_OP,
    build_schedules,
    pipeline_job,
    pipeline_run_config,
    run_transform_op,
    transform_job,
    transform_run_config,
)
from novasight_orchestration.registry import ScheduleRow, TransformRow, schedule_name

PID = "22222222-2222-2222-2222-222222222222"
TID = "44444444-4444-4444-4444-444444444444"
SID_A = "11111111-1111-1111-1111-111111111111"
SID_B = "33333333-3333-3333-3333-333333333333"
SID_C = "55555555-5555-5555-5555-555555555555"


def _row(sid: str, kind: str, target: str, cron: str, enabled: bool) -> ScheduleRow:
    return ScheduleRow(
        schedule_id=sid, tenant="acme", target_kind=kind, target_id=target, cron=cron,
        enabled=enabled,
    )


# ---------------------------------------------------------------------------
# run-config contract — must mirror the backend exactly
# ---------------------------------------------------------------------------


def test_pipeline_run_config_contract() -> None:
    assert pipeline_run_config("pid-1", "acme") == {
        "ops": {PIPELINE_OP: {"config": {"pipeline_id": "pid-1", "tenant": "acme"}}}
    }


def test_transform_run_config_contract() -> None:
    assert transform_run_config("tid-1", "acme") == {
        "ops": {TRANSFORM_OP: {"config": {"transform_job_id": "tid-1", "tenant": "acme"}}}
    }


# ---------------------------------------------------------------------------
# generic jobs — names + op wiring match the contract
# ---------------------------------------------------------------------------


def test_generic_jobs_have_contract_names_and_ops() -> None:
    assert pipeline_job.name == PIPELINE_JOB
    assert [n.name for n in pipeline_job.graph.node_defs] == [PIPELINE_OP]
    assert transform_job.name == TRANSFORM_JOB
    assert [n.name for n in transform_job.graph.node_defs] == [TRANSFORM_OP]


def test_generic_op_config_schemas() -> None:
    # The op config keys must match the run-config contract so launchRun validates.
    p_op = next(n for n in pipeline_job.graph.node_defs if n.name == PIPELINE_OP)
    assert set(p_op.config_schema.config_type.fields) == {"pipeline_id", "tenant"}
    t_op = next(n for n in transform_job.graph.node_defs if n.name == TRANSFORM_OP)
    assert set(t_op.config_schema.config_type.fields) == {"transform_job_id", "tenant"}


# ---------------------------------------------------------------------------
# schedule_name derivation
# ---------------------------------------------------------------------------


def test_schedule_name_is_deterministic_and_valid() -> None:
    name = schedule_name(SID_A)
    assert name == "sched_11111111111111111111111111111111"
    assert name == schedule_name(SID_A)  # deterministic
    # Dagster names: letters, digits, underscores only.
    assert name.replace("_", "").isalnum()


# ---------------------------------------------------------------------------
# build_schedules — the registry -> schedules mapping
# ---------------------------------------------------------------------------


def test_build_schedules_targets_status_and_run_config() -> None:
    rows = [
        _row(SID_A, "pipeline", PID, "0 6 * * *", enabled=True),
        _row(SID_B, "transform_job", TID, "30 7 * * *", enabled=False),
    ]
    scheds = {s.name: s for s in build_schedules(rows)}
    assert set(scheds) == {schedule_name(SID_A), schedule_name(SID_B)}

    pipe = scheds[schedule_name(SID_A)]
    assert pipe.cron_schedule == "0 6 * * *"
    assert pipe.job_name == PIPELINE_JOB
    assert pipe.default_status == DefaultScheduleStatus.RUNNING  # enabled

    xform = scheds[schedule_name(SID_B)]
    assert xform.cron_schedule == "30 7 * * *"
    assert xform.job_name == TRANSFORM_JOB
    assert xform.default_status == DefaultScheduleStatus.STOPPED  # disabled


def test_build_schedules_skips_unknown_target_kind() -> None:
    rows = [
        _row(SID_A, "pipeline", PID, "0 6 * * *", enabled=True),
        _row(SID_C, "bogus", "x", "* * * * *", enabled=True),
    ]
    scheds = build_schedules(rows)
    assert [s.name for s in scheds] == [schedule_name(SID_A)]


def test_build_schedules_empty_when_no_rows() -> None:
    assert build_schedules([]) == []


# ---------------------------------------------------------------------------
# run_transform_op — runs the selection via the dbt CLI (no asset-event streaming)
# ---------------------------------------------------------------------------


class _FakeInvocation:
    def __init__(self) -> None:
        self.waited = False

    def wait(self) -> "_FakeInvocation":
        self.waited = True
        return self

    def stream(self) -> object:
        # A plain op has no asset mapping; streaming would KeyError on 'nodes'.
        raise AssertionError("run_transform_op must use .wait(), not .stream()")


class _FakeDbt:
    def __init__(self) -> None:
        self.invocation = _FakeInvocation()
        self.args: list[str] | None = None

    def cli(self, args: list[str], context: object = None) -> _FakeInvocation:
        self.args = args
        return self.invocation


def _run_op(monkeypatch: pytest.MonkeyPatch, selection: str) -> _FakeDbt:
    monkeypatch.setattr(
        dyn,
        "load_transform",
        lambda jid: TransformRow(
            transform_job_id=jid, tenant="acme", name="job", selection=selection
        ),
    )
    dbt = _FakeDbt()
    ctx = build_op_context(
        op_config={"transform_job_id": TID, "tenant": "acme"}, resources={"dbt": dbt}
    )
    run_transform_op(ctx)
    return dbt


def test_run_transform_op_builds_selection_and_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    dbt = _run_op(monkeypatch, "category_sales")
    assert dbt.args == ["build", "--select", "category_sales"]
    assert dbt.invocation.waited  # .wait() (not .stream()) — generic op, no asset graph


def test_run_transform_op_empty_selection_builds_whole_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dbt = _run_op(monkeypatch, "")
    assert dbt.args == ["build"]  # no --select → whole tenant project
    assert dbt.invocation.waited
