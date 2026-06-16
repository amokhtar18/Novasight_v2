"""Unit tests for the source→destination type suggestion (#5)."""
from __future__ import annotations

import pytest

from app.ingestion.type_mapping import TARGET_TYPES, suggest_target_type


@pytest.mark.parametrize(
    ("source_type", "expected"),
    [
        ("INTEGER", "Int64"),
        ("BIGINT", "Int64"),
        ("VARCHAR(255)", "String"),
        ("TEXT", "String"),
        ("NUMERIC(10,2)", "Decimal"),
        ("NUMBER", "Decimal"),  # Oracle
        ("DOUBLE PRECISION", "Float64"),
        ("REAL", "Float64"),
        ("BOOLEAN", "Boolean"),
        ("BIT", "Boolean"),  # SQL Server
        ("DATE", "Date"),
        ("TIMESTAMP WITH TIME ZONE", "DateTime"),
        ("DATETIME", "DateTime"),
        ("JSONB", "JSON"),
        ("UUID", "UUID"),
        ("UNIQUEIDENTIFIER", "UUID"),  # SQL Server
        ("CLOB", "String"),  # unknown → safe default
    ],
)
def test_suggest_target_type(source_type: str, expected: str) -> None:
    suggestion = suggest_target_type(source_type)
    assert suggestion == expected
    # Every suggestion is a member of the closed target set.
    assert suggestion in TARGET_TYPES
