"""Source SQL type → destination type suggestion for the pipeline wizard (#5).

The field-mapping step shows each source column with a *suggested* destination type
the user can override from a closed list. The suggestion is a best-effort mapping
from the source's SQLAlchemy type string (e.g. ``VARCHAR(255)``, ``NUMERIC(10,2)``,
``TIMESTAMP WITH TIME ZONE``) to a canonical, ClickHouse-leaning target type.

This drives the UI default only — it is intentionally forgiving (unknown → ``String``)
and never the sole arbiter of the physical write. The closed ``TARGET_TYPES`` set is
what the wizard offers and what the config validates against, so a stored mapping can
never carry an arbitrary type string.
"""
from __future__ import annotations

# Canonical destination types the wizard offers (and the config validates against).
TARGET_TYPES: tuple[str, ...] = (
    "String",
    "Int64",
    "Float64",
    "Decimal",
    "Boolean",
    "Date",
    "DateTime",
    "JSON",
    "UUID",
)


def suggest_target_type(source_type: str) -> str:
    """Best-effort canonical target type for a source SQL type string.

    Substring match on the upper-cased type, ordered most-specific-first (so
    ``TIMESTAMP`` wins over ``DATE``, ``BIGINT`` over a bare integer). Anything
    unrecognised falls back to ``String`` — always a safe landing type.
    """
    s = source_type.upper()
    if "TIMESTAMP" in s or "DATETIME" in s:
        return "DateTime"
    if "DATE" in s:
        return "Date"
    if "BOOL" in s or s.startswith("BIT"):
        return "Boolean"
    if "DECIMAL" in s or "NUMERIC" in s or "NUMBER" in s:
        return "Decimal"
    if "DOUBLE" in s or "FLOAT" in s or "REAL" in s:
        return "Float64"
    if "INT" in s:
        return "Int64"
    if "JSON" in s:
        return "JSON"
    if "UUID" in s or "UNIQUEIDENTIFIER" in s:
        return "UUID"
    return "String"
