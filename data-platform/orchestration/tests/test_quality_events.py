"""Unit tests for the structured quality-gate failure events (``quality_events``).

Pure logic — no dbt, no Dagster run, no warehouse. Proves the event the alerting layer
will consume is well-formed: tenant-scoped, JSON-serializable, and carrying the failing
check's identity and failed-row count.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from dagster import AssetCheckResult, AssetCheckSeverity, AssetKey

from novasight_orchestration.quality_events import (
    QUALITY_GATE_FAILURE_EVENT,
    QualityGateFailure,
    build_failure_event,
    emit_quality_gate_failure,
)

FIXED_NOW = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)


def _failed_check(**overrides: object) -> AssetCheckResult:
    kwargs: dict[str, object] = {
        "passed": False,
        "asset_key": AssetKey(["stg_phase1__regional_sales"]),
        "check_name": "unique_stg_phase1__regional_sales_region",
        "severity": AssetCheckSeverity.ERROR,
        "metadata": {"dagster_dbt/failed_row_count": 2, "status": "fail"},
    }
    kwargs.update(overrides)
    return AssetCheckResult(**kwargs)  # type: ignore[arg-type]


class _FakeLog:
    """Captures ``error`` calls so emission is assertable without a Dagster context."""

    def __init__(self) -> None:
        self.errors: list[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)


def test_build_failure_event_extracts_check_identity() -> None:
    event = build_failure_event(_failed_check(), tenant="tenant_local", now=FIXED_NOW)

    assert event.tenant == "tenant_local"
    assert event.asset_key == "stg_phase1__regional_sales"
    assert event.check_name == "unique_stg_phase1__regional_sales_region"
    assert event.severity == "ERROR"
    assert event.failed_row_count == 2
    assert event.event_type == QUALITY_GATE_FAILURE_EVENT
    assert event.detected_at == FIXED_NOW.isoformat()


def test_build_failure_event_message_is_tenant_scoped_and_explains_blocking() -> None:
    event = build_failure_event(_failed_check(), tenant="tenant_local", now=FIXED_NOW)

    assert "tenant_local" in event.message
    assert "unique_stg_phase1__regional_sales_region" in event.message
    assert "blocked" in event.message.lower()
    assert "2 failing row(s)" in event.message


def test_build_failure_event_tolerates_missing_failed_row_count() -> None:
    # not_null / unique results may omit the failed-row metadata; must not blow up.
    event = build_failure_event(
        _failed_check(metadata={"status": "fail"}), tenant="t1", now=FIXED_NOW
    )

    assert event.failed_row_count is None
    assert "failing row(s)" not in event.message


def test_event_is_json_serializable_with_stable_marker() -> None:
    event = build_failure_event(_failed_check(), tenant="tenant_local", now=FIXED_NOW)

    payload = json.loads(event.to_json())

    assert payload["event_type"] == "quality_gate_failure"
    assert payload["tenant"] == "tenant_local"
    assert payload["metadata"]["status"] == "fail"
    # Round-trips losslessly through dict <-> json.
    assert payload == json.loads(json.dumps(event.to_dict()))


def test_non_scalar_metadata_is_stringified_for_transport() -> None:
    event = build_failure_event(
        _failed_check(metadata={"weird": {"nested": 1}}), tenant="t1", now=FIXED_NOW
    )

    # Survives json.dumps regardless of the original metadata value type.
    assert isinstance(event.metadata["weird"], str)
    json.loads(event.to_json())


def test_emit_writes_one_structured_error_line() -> None:
    log = _FakeLog()
    failure = QualityGateFailure(
        tenant="tenant_local",
        asset_key="stg_phase1__regional_sales",
        check_name="unique_region",
        severity="ERROR",
        failed_row_count=1,
        message="boom",
        detected_at=FIXED_NOW.isoformat(),
    )

    emit_quality_gate_failure(log, failure)

    assert len(log.errors) == 1
    assert json.loads(log.errors[0])["event_type"] == "quality_gate_failure"
