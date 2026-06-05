"""Pure KPI evaluation: extract a single value and decide whether it breaches.

A KPI query is a structured aggregate that yields one value (one metric, no
dimensions → a single global-aggregate row). The evaluator reads that value and
compares it to the threshold with the configured comparator. Keeping this pure
(no I/O, no ORM) makes the breach logic exhaustively testable.
"""
from __future__ import annotations

import operator
from collections.abc import Callable, Sequence
from typing import Any

# Closed set of comparators a KPI may use; anything else is a configuration error.
_COMPARATORS: dict[str, Callable[[float, float], bool]] = {
    ">": operator.gt,
    "<": operator.lt,
    ">=": operator.ge,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
}


class KpiEvaluationError(ValueError):
    """The KPI query result or comparator could not be evaluated."""


def extract_value(column_names: Sequence[str], rows: Sequence[Sequence[Any]]) -> float | None:
    """Return the single numeric KPI value from a query result, or ``None`` if empty.

    The KPI query is expected to produce one aggregate value; we read the last
    column of the first row (the metric column for a dimension-less aggregate).
    ``None`` (no rows / null cell) means "no data to evaluate".
    """
    if not rows:
        return None
    row = rows[0]
    if not row:
        return None
    cell = row[-1]
    if cell is None:
        return None
    try:
        return float(cell)
    except (TypeError, ValueError) as exc:
        raise KpiEvaluationError(f"KPI value {cell!r} is not numeric") from exc


def is_breached(value: float, comparator: str, threshold: float) -> bool:
    """Return ``True`` if ``value <comparator> threshold`` holds.

    Raises ``KpiEvaluationError`` for an unknown comparator (fail closed rather than
    silently never alerting).
    """
    compare = _COMPARATORS.get(comparator)
    if compare is None:
        raise KpiEvaluationError(f"unknown comparator {comparator!r}")
    return compare(value, threshold)
