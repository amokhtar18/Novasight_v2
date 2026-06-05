"""Tests for the 5-field cron matcher (app/reporting/cron.py)."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.reporting.cron import CronError, matches

# A fixed reference instant: Friday 2026-06-05 12:30 UTC. weekday()==4 (Fri) → cron 5.
_FRI_1230 = datetime(2026, 6, 5, 12, 30, tzinfo=UTC)
_SUN_0000 = datetime(2026, 6, 7, 0, 0, tzinfo=UTC)  # Sunday → cron 0


@pytest.mark.parametrize(
    ("expr", "when", "expected"),
    [
        ("* * * * *", _FRI_1230, True),          # every minute
        ("30 12 * * *", _FRI_1230, True),         # exact minute+hour
        ("31 12 * * *", _FRI_1230, False),        # wrong minute
        ("*/15 * * * *", _FRI_1230, True),        # 30 is a multiple of 15
        ("*/20 * * * *", _FRI_1230, False),       # 30 is not a multiple of 20
        ("0-45 12 * * *", _FRI_1230, True),       # range covers 30
        ("0,15,30,45 12 * * *", _FRI_1230, True), # list includes 30
        ("30 12 5 6 *", _FRI_1230, True),         # day-of-month + month match
        ("30 12 * * 5", _FRI_1230, True),         # day-of-week Friday (5)
        ("30 12 * * 1", _FRI_1230, False),        # day-of-week Monday — no
        ("0 0 * * 0", _SUN_0000, True),           # Sunday as 0
        ("0 0 * * 7", _SUN_0000, True),           # Sunday as 7 (alternate spelling)
    ],
)
def test_matches(expr: str, when: datetime, expected: bool) -> None:
    assert matches(expr, when) is expected


def test_dom_or_dow_when_both_restricted() -> None:
    # POSIX rule: when both DOM and DOW are restricted, EITHER matching is enough.
    # 2026-06-05 is the 5th (Friday). DOM=5 matches even though DOW=1 (Mon) does not.
    assert matches("30 12 5 * 1", _FRI_1230) is True
    # And DOW matching is enough even when DOM does not.
    assert matches("30 12 10 * 5", _FRI_1230) is True
    # Neither matches → not due.
    assert matches("30 12 10 * 1", _FRI_1230) is False


@pytest.mark.parametrize(
    "bad",
    [
        "* * * *",
        "* * * * * *",
        "60 * * * *",
        "* 24 * * *",
        "abc * * * *",
        "*/0 * * * *",
        "5-1 * * * *",
    ],
)
def test_invalid_expressions_raise(bad: str) -> None:
    with pytest.raises(CronError):
        matches(bad, _FRI_1230)
