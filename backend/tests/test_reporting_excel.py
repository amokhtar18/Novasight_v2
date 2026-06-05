"""Tests for the xlsx renderer (app/reporting/excel.py)."""
from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime
from decimal import Decimal

from app.reporting.excel import _coerce, _safe_sheet_name, render_workbook


def test_render_produces_valid_xlsx_bytes() -> None:
    data = render_workbook("Sales", ["region", "total"], [["eu", 10], ["us", 20]])

    # An .xlsx is a ZIP container — assert the magic bytes and that it opens.
    assert data[:2] == b"PK"
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        assert "xl/workbook.xml" in names


def test_render_handles_empty_result() -> None:
    data = render_workbook("Empty", ["a", "b"], [])
    assert data[:2] == b"PK"


def test_safe_sheet_name_truncates_and_strips_forbidden() -> None:
    assert _safe_sheet_name("a/b:c*d?e[f]") == "a_b_c_d_e_f"
    assert len(_safe_sheet_name("x" * 50)) == 31
    assert _safe_sheet_name("") == "Report"


def test_coerce_maps_exotic_types() -> None:
    assert _coerce(None) is None
    assert _coerce(Decimal("1.5")) == 1.5
    assert _coerce(5) == 5
    assert _coerce("x") == "x"
    now = datetime(2026, 6, 5, tzinfo=UTC)
    assert _coerce(now) is now
    # An unknown type is stringified so rendering never crashes.
    assert _coerce({"a": 1}) == "{'a': 1}"
