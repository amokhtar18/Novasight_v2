"""Validation tests for the NativeFilter config model (Slice C)."""
from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.dashboard import DashboardUpdate, NativeFilter


def _value_filter(**kw: object) -> dict[str, object]:
    base: dict[str, object] = {"id": "f1", "kind": "value", "member": "regional_sales.region"}
    base.update(kw)
    return base


def test_value_filter_minimal_ok() -> None:
    f = NativeFilter(**_value_filter())  # type: ignore[arg-type]
    assert f.operator == "equals"
    assert f.scope.mode == "auto"


def test_value_filter_rejects_comparison_operator() -> None:
    with pytest.raises(ValidationError):
        NativeFilter(**_value_filter(operator="gt"))  # type: ignore[arg-type]


def test_numeric_range_rejects_min_gt_max() -> None:
    with pytest.raises(ValidationError):
        NativeFilter(
            id="n1", kind="numeric", member="regional_sales.sales_rank",
            numeric_range={"min": 10, "max": 1},
        )


def test_absolute_date_range_must_be_two_ordered_dates() -> None:
    with pytest.raises(ValidationError):
        NativeFilter(
            id="t1", kind="time", member="regional_sales.region",
            date_range=["2024-03-01", "2024-01-01"],
        )


def test_scope_tiles_accepts_uuid_list() -> None:
    tid = uuid.uuid4()
    f = NativeFilter(**_value_filter(scope={"mode": "tiles", "tile_ids": [str(tid)]}))  # type: ignore[arg-type]
    assert f.scope.tile_ids == [tid]


def test_dashboard_update_rejects_parent_cycle() -> None:
    with pytest.raises(ValidationError):
        DashboardUpdate(
            native_filters=[
                NativeFilter(**_value_filter(id="a", parent_id="b")),  # type: ignore[arg-type]
                NativeFilter(**_value_filter(id="b", parent_id="a")),  # type: ignore[arg-type]
            ]
        )


def test_dashboard_update_rejects_non_value_parent() -> None:
    with pytest.raises(ValidationError):
        DashboardUpdate(
            native_filters=[
                NativeFilter(id="t", kind="time", member="regional_sales.region"),
                NativeFilter(**_value_filter(id="c", parent_id="t")),  # type: ignore[arg-type]
            ]
        )


def test_dashboard_update_rejects_unknown_parent() -> None:
    with pytest.raises(ValidationError):
        DashboardUpdate(native_filters=[NativeFilter(**_value_filter(id="c", parent_id="missing"))])  # type: ignore[arg-type]
