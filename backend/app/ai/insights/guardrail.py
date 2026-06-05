"""No-invented-numbers guardrail for AI-generated insight summaries.

## The core guarantee

Summaries MUST NOT contain numbers that are not traceable to the result set
(the already-computed QueryResponse data).  The LLM is instructed not to
invent numbers, but instruction-following is not sufficient — this module
provides a post-generation verification function that is the authoritative
enforcement point.

## Algorithm

1. Extract every numeric token from the generated summary text.
   A "numeric token" is any contiguous run of digits (possibly with a decimal
   point) that may be wrapped in common display formatting:
     - thousands separators (commas in e.g. "1,234" or "1,234,567")
     - currency symbols ($ £ € ¥ ₹ ¢ — stripped before comparison)
     - a leading minus sign (negative numbers)
     - a trailing ``%`` (percentage — stripped before comparison)
   After stripping formatting the token is parsed to a Python ``float``.

2. Build the set of numeric reference values from the result set:
   every cell value that can be parsed as a ``float`` is collected as a
   reference.

3. For every extracted summary number, check whether it is "traceable" to the
   reference set:
   - Exact match (string equality after normalisation), OR
   - Rounded match: round the reference value to k decimal places (k in 0..4)
     — if that equals the summary value, it is a legitimate rounding (e.g. the
     data has 142500.876 and the summary says "142,501" — that rounds
     correctly).
   - Scaled match: ``value / 1000`` or ``value * 1000`` (K/M truncation common
     in summaries).  Only applied when the ratio is within 0.5 % after rounding.

4. If ANY extracted number is NOT traceable, raise ``InsightGuardrailError``
   with a safe message (no raw data or LLM output in the message).

## Why a pure function

``verify_no_invented_numbers`` is a pure function (no side effects, no I/O)
so it can be tested exhaustively without mocking.  The service layer calls it
after each generation attempt and can decide to regenerate once before
failing closed.
"""
from __future__ import annotations

import contextlib
import re
from typing import Any


class InsightGuardrailError(Exception):
    """Raised when the generated summary contains a number not in the result set.

    The ``reason`` is safe to forward to the API caller — it does not contain
    raw data values or the full summary text.

    Attributes:
        reason: A short, user-safe explanation.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# ---------------------------------------------------------------------------
# Numeric token extraction
# ---------------------------------------------------------------------------

# Matches a numeric token in the summary text, including optional formatting.
# Captures:
#   - optional leading currency symbols and minus
#   - an integer or decimal number, potentially with comma thousands separators
#   - optional trailing %
#
# Examples matched:
#   "1,234"  "142,500.50"  "$3.5"  "-12.3"  "45%"  "£1,200"  "2.4e6"  "1.5E+9"
_NUM_TOKEN_RE = re.compile(
    r"""
    (?<!\w)                   # not preceded by a word char (no partial matches)
    (?P<sign>-)?              # optional leading minus
    [£$€¥₹¢]?               # optional currency symbol
    (?P<digits>
        \d{1,3}(?:,\d{3})*   # thousands-separated integer part
        (?:\.\d+)?           # optional decimal
        (?:[eE][+-]?\d+)?    # optional scientific-notation exponent
        |
        \d+(?:\.\d+)?        # plain integer or decimal
        (?:[eE][+-]?\d+)?    # optional scientific-notation exponent
    )
    (?:%)?                    # optional trailing percent
    (?!\w)                    # not followed by a word char
    """,
    re.VERBOSE,
)


def _extract_numbers(text: str) -> list[float]:
    """Return every distinct numeric value found in ``text``.

    Strips thousands separators, currency symbols, and percentage markers
    before parsing.  Returns an empty list if no numbers are found.
    """
    results: list[float] = []
    for m in _NUM_TOKEN_RE.finditer(text):
        raw = m.group()
        # Strip non-numeric chars except digits, dot, and leading minus.
        cleaned = raw.replace(",", "").lstrip("£$€¥₹¢").rstrip("%")
        with contextlib.suppress(ValueError):
            results.append(float(cleaned))
    return results


# ---------------------------------------------------------------------------
# Reference-value extraction
# ---------------------------------------------------------------------------


def _extract_reference_values(columns: list[str], rows: list[list[Any]]) -> list[float]:
    """Collect all numeric cell values from a result set as floats.

    Iterates all rows/columns and attempts float conversion.  Non-numeric
    values (strings, booleans) are silently skipped.
    """
    refs: list[float] = []
    for row in rows:
        for value in row:
            if isinstance(value, bool):
                continue  # bool is a subclass of int — skip (True=1, False=0)
            if isinstance(value, (int, float)):
                refs.append(float(value))
            elif isinstance(value, str):
                cleaned = value.replace(",", "").rstrip("%").lstrip("£$€¥₹¢")
                with contextlib.suppress(ValueError):
                    refs.append(float(cleaned))
    return refs


# ---------------------------------------------------------------------------
# Traceability check
# ---------------------------------------------------------------------------

# Tolerance for rounding: we test the summary number against each reference
# rounded to 0..MAX_ROUNDING_DECIMALS decimal places.
_MAX_ROUNDING_DECIMALS = 4

# Relative tolerance for scaled comparisons (K/M abbreviations).
_SCALE_TOLERANCE = 0.005  # 0.5 %

# Scale factors for "K" / "M" abbreviation matching only.
# e.g. a summary saying "1.5K" (we'd extract 1.5) should match data value 1500.
# We do NOT include 100x here (percent-of-total summaries use the actual data
# value from the result set, not a derived ratio).
_SCALE_FACTORS = [1_000.0, 1_000_000.0]


def _is_traceable(value: float, references: list[float]) -> bool:
    """Return True if ``value`` is traceable to at least one reference value.

    Traceability rules (applied in order, first match wins):
    1. Exact float equality.
    2. Rounded match: round(reference, k) == round(value, k) for k in 0..4.
    3. Scaled match: for scale in {1000, 1e6}, abs(value - ref/scale)
       / max(abs(value), 1e-9) <= 0.005.
    """
    if not references:
        return False

    for ref in references:
        # Rule 1: exact equality (handles identical float representation)
        if ref == value:
            return True

        # Rule 2: rounding match — up to MAX_ROUNDING_DECIMALS decimal places
        for decimals in range(_MAX_ROUNDING_DECIMALS + 1):
            if round(ref, decimals) == round(value, decimals):
                return True

        # Rule 3: scaled match — for K/M abbreviations only (scale >= 1000).
        # e.g. data has 1500, summary says "1.5K" (extracted as 1.5):
        #   ref/scale = 1500/1000 = 1.5 ≈ value=1.5 → match
        # Require the scale factor to be large enough (≥ 1000) to avoid spurious
        # matches like 9999 ≈ 100 x 100 (which is not a valid K/M rounding).
        for scale in _SCALE_FACTORS:
            scaled_ref = ref / scale
            denom = max(abs(value), 1e-9)
            if abs(scaled_ref - value) / denom <= _SCALE_TOLERANCE:
                return True
            # Inverse: summary wrote the full scaled number, ref is the K/M value.
            # e.g. data has 1.5 (stored as 1.5K), summary says 1500.
            scaled_val = value / scale
            denom2 = max(abs(ref), 1e-9)
            if abs(scaled_val - ref) / denom2 <= _SCALE_TOLERANCE:
                return True

    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def verify_no_invented_numbers(
    summary: str,
    *,
    columns: list[str],
    rows: list[list[Any]],
) -> None:
    """Verify that every number in ``summary`` is traceable to the result set.

    This is the authoritative "no invented numbers" guardrail.  It is a pure
    function: no side effects, no I/O, deterministic.  Call it after every
    LLM generation attempt for insight summaries.

    Args:
        summary: The generated natural-language summary text.
        columns: Column names from the QueryResponse (used for context only;
            the actual traceability check is against ``rows``).
        rows: All data rows from the QueryResponse.  Each row is a list
            aligned with ``columns``.

    Raises:
        InsightGuardrailError: If any numeric token in ``summary`` cannot be
            traced to a value in the result set.  The error message is safe
            to forward to the API caller.

    Example::

        verify_no_invented_numbers(
            "Revenue was $1,234 across 3 regions.",
            columns=["region", "revenue", "count"],
            rows=[["EMEA", 1234, 3]],
        )
        # Passes — both 1234 and 3 are in the data.

        verify_no_invented_numbers(
            "Revenue was $9,999.",
            columns=["region", "revenue"],
            rows=[["EMEA", 1234]],
        )
        # Raises InsightGuardrailError — 9999 is not in the data.
    """
    summary_numbers = _extract_numbers(summary)
    if not summary_numbers:
        return  # no numbers to check

    references = _extract_reference_values(columns, rows)

    invented: list[float] = [
        v for v in summary_numbers if not _is_traceable(v, references)
    ]

    if invented:
        raise InsightGuardrailError(
            "The generated summary contains numbers that cannot be verified "
            "against the result set data. Please try again."
        )
