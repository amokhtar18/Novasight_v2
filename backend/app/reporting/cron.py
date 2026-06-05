"""A minimal, dependency-free 5-field cron matcher.

The reporting dispatcher fires on a coarse heartbeat (periodiq) and then asks, for
each enabled report, "is this report's own cron due at this minute?" — that
decision is this module. Keeping per-report schedules as plain cron strings in the
registry (not periodiq-decorated actors) is what lets schedules be tenant config
that changes without a deploy.

Supported syntax, standard 5 fields ``minute hour day-of-month month day-of-week``:

* ``*``               — every value
* ``*/n``             — every n-th value across the field's range
* ``a``               — a single value
* ``a-b``             — an inclusive range
* ``a-b/n``           — an inclusive range, stepped
* ``a,b,c``           — a comma list of any of the above

Day-of-week is ``0-6`` with Sunday = 0 (``7`` is also accepted as Sunday). Per
POSIX cron, when *both* day-of-month and day-of-week are restricted (neither is
``*``), a tick matches if *either* field matches.
"""
from __future__ import annotations

from datetime import datetime

# Inclusive (min, max) for each of the five fields, in order. Day-of-week allows
# 7 as an alternate spelling of Sunday; it is normalised to 0 after parsing.
_FIELD_BOUNDS: tuple[tuple[int, int], ...] = (
    (0, 59),  # minute
    (0, 23),  # hour
    (1, 31),  # day of month
    (1, 12),  # month
    (0, 7),   # day of week (Sun = 0 or 7)
)


class CronError(ValueError):
    """A cron expression could not be parsed."""


def _parse_field(field: str, lo: int, hi: int) -> frozenset[int]:
    """Expand one cron field into the explicit set of values it matches."""
    values: set[int] = set()
    for part in field.split(","):
        if not part:
            raise CronError(f"empty term in cron field {field!r}")
        step = 1
        if "/" in part:
            base, _, step_str = part.partition("/")
            if not step_str.isdigit() or int(step_str) < 1:
                raise CronError(f"invalid step in cron term {part!r}")
            step = int(step_str)
        else:
            base = part

        if base == "*":
            start, end = lo, hi
        elif "-" in base:
            start_str, _, end_str = base.partition("-")
            start, end = _as_int(start_str, lo, hi), _as_int(end_str, lo, hi)
            if start > end:
                raise CronError(f"reversed range in cron term {part!r}")
        else:
            start = end = _as_int(base, lo, hi)

        values.update(range(start, end + 1, step))
    return frozenset(values)


def _as_int(token: str, lo: int, hi: int) -> int:
    if not token.lstrip("-").isdigit():
        raise CronError(f"non-numeric cron value {token!r}")
    value = int(token)
    if not lo <= value <= hi:
        raise CronError(f"cron value {value} out of range [{lo}, {hi}]")
    return value


def matches(expression: str, when: datetime) -> bool:
    """Return ``True`` if ``when`` (minute resolution) satisfies ``expression``.

    Raises ``CronError`` if the expression is not five valid fields.
    """
    fields = expression.split()
    if len(fields) != 5:
        raise CronError(f"expected 5 cron fields, got {len(fields)}: {expression!r}")

    minute, hour, dom, month, dow_raw = (
        _parse_field(field, lo, hi)
        for field, (lo, hi) in zip(fields, _FIELD_BOUNDS, strict=True)
    )
    # Collapse the alternate Sunday spelling (7 → 0).
    dow = frozenset(0 if value == 7 else value for value in dow_raw)

    if when.minute not in minute or when.hour not in hour or when.month not in month:
        return False

    # datetime.weekday(): Mon=0..Sun=6 → convert to cron's Sun=0..Sat=6.
    cron_dow = (when.weekday() + 1) % 7
    dom_match = when.day in dom
    dow_match = cron_dow in dow

    dom_restricted = fields[2] != "*"
    dow_restricted = fields[4] != "*"
    if dom_restricted and dow_restricted:
        # POSIX: either field matching is enough when both are restricted.
        return dom_match or dow_match
    return dom_match and dow_match
