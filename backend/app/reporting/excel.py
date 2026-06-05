"""Render a query result to ``.xlsx`` bytes with XlsxWriter.

Pure and in-memory: takes column names + row tuples (exactly the shape of
``QueryResult``) and returns the workbook as bytes, ready to attach to an email or
write to the object store. No I/O, no tenant knowledge — the caller has already
produced tenant-scoped rows.
"""
from __future__ import annotations

import io
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import xlsxwriter

# Excel sheet names are capped at 31 chars and forbid a handful of characters.
_MAX_SHEET_NAME = 31
_FORBIDDEN_SHEET_CHARS = set(r"[]:*?/\\")

# The MIME type and extension for a modern (xlsx) workbook.
XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _safe_sheet_name(title: str) -> str:
    """Coerce ``title`` into a legal, non-empty Excel worksheet name."""
    cleaned = "".join("_" if ch in _FORBIDDEN_SHEET_CHARS else ch for ch in title)
    cleaned = cleaned.strip().strip("_")[:_MAX_SHEET_NAME]
    return cleaned or "Report"


def _coerce(value: Any) -> Any:  # noqa: ANN401 — values come from arbitrary query columns
    """Map a query cell to a type XlsxWriter can write natively.

    Primitives (int/float/bool/str) and datetimes pass through; ``Decimal`` becomes
    a float; ``None`` becomes an empty cell; anything else is stringified so the
    render can never fail on an exotic type.
    """
    if value is None or isinstance(value, (int, float, bool, str, datetime, date)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def render_workbook(
    title: str,
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
) -> bytes:
    """Render ``columns`` + ``rows`` into a single-sheet ``.xlsx`` and return bytes."""
    buffer = io.BytesIO()
    workbook = xlsxwriter.Workbook(
        buffer,
        {"in_memory": True, "default_date_format": "yyyy-mm-dd hh:mm:ss"},
    )
    try:
        worksheet = workbook.add_worksheet(_safe_sheet_name(title))
        header_format = workbook.add_format({"bold": True})

        for col, name in enumerate(columns):
            worksheet.write(0, col, name, header_format)
        for row_index, row in enumerate(rows, start=1):
            for col, value in enumerate(row):
                worksheet.write(row_index, col, _coerce(value))
    finally:
        workbook.close()
    return buffer.getvalue()
