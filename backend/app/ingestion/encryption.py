"""Encrypt tagged columns of an Arrow table before it is written to the lake.

Used by the CSV→Iceberg pipeline: a dataset's ``sensitive_columns`` are replaced
with base64 ciphertext string columns so they are encrypted at rest. Non-tagged
columns and ``null`` cells are left untouched; a tagged column that is not present
in the table is silently skipped.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.core.crypto import KmsProvider, encrypt_value


def encrypt_arrow_columns(
    table: Any,  # noqa: ANN401 — pyarrow.Table; pyarrow is treated as untyped (mypy override)
    columns: Iterable[str],
    provider: KmsProvider,
) -> Any:  # noqa: ANN401
    """Return ``table`` with each named column replaced by its encrypted string form."""
    import pyarrow as pa

    present = set(table.column_names)
    for name in columns:
        if name not in present:
            continue
        index = table.column_names.index(name)
        values = table.column(index).to_pylist()
        encrypted = [
            None if value is None else encrypt_value(provider, str(value))
            for value in values
        ]
        table = table.set_column(
            index, pa.field(name, pa.string()), pa.array(encrypted, type=pa.string())
        )
    return table
