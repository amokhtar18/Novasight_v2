"""Tests for pure KPI evaluation (app/reporting/alerts/evaluator.py)."""
from __future__ import annotations

import pytest

from app.reporting.alerts.evaluator import (
    KpiEvaluationError,
    extract_value,
    is_breached,
)


def test_extract_value_reads_last_column_of_first_row() -> None:
    assert extract_value(["region", "total"], [("eu", 42)]) == 42.0


def test_extract_value_empty_is_none() -> None:
    assert extract_value(["total"], []) is None
    assert extract_value(["total"], [()]) is None
    assert extract_value(["total"], [(None,)]) is None


def test_extract_value_non_numeric_raises() -> None:
    with pytest.raises(KpiEvaluationError):
        extract_value(["total"], [("not-a-number",)])


@pytest.mark.parametrize(
    ("value", "comparator", "threshold", "expected"),
    [
        (150.0, ">", 100.0, True),
        (100.0, ">", 100.0, False),
        (50.0, "<", 100.0, True),
        (100.0, ">=", 100.0, True),
        (100.0, "<=", 100.0, True),
        (5.0, "==", 5.0, True),
        (5.0, "!=", 6.0, True),
        (5.0, "!=", 5.0, False),
    ],
)
def test_is_breached(value: float, comparator: str, threshold: float, expected: bool) -> None:
    assert is_breached(value, comparator, threshold) is expected


def test_is_breached_unknown_comparator_raises() -> None:
    with pytest.raises(KpiEvaluationError, match="unknown comparator"):
        is_breached(1.0, "<>", 2.0)
