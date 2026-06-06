"""Filesystem / object-store connector — read files already in the lake bucket.

Config: ``format`` (csv | parquet | json | excel) and ``key`` (the object key in
the configured bucket — typically under the tenant's raw prefix). No secret: it
uses the app's own object-store credentials.

Test confirms the object is readable; preview parses the first rows with pyarrow.
The object read is awaited; parsing runs in a worker thread (CPU-bound). The load
step (object → Arrow → Iceberg) reuses the same readers.
"""
from __future__ import annotations

import asyncio
import io
from typing import Any, ClassVar

from app.core.object_store import ObjectStore
from app.ingestion.connectors.base import (
    ConnectorError,
    PreviewResult,
    SourceConnector,
)

_FORMATS = {"csv", "parquet", "json", "excel"}
_MAX_PREVIEW_ROWS = 200


class FilesystemConnector(SourceConnector):
    """Connector for files (CSV/Parquet/JSON/Excel) in the object store."""

    kind: ClassVar[str] = "filesystem"

    def __init__(self, store: ObjectStore) -> None:
        self._store = store

    def validate_config(self, config: dict[str, Any]) -> None:
        fmt = str(config.get("format", "")).lower()
        if fmt not in _FORMATS:
            raise ConnectorError(f"format must be one of {sorted(_FORMATS)}")
        if not str(config.get("key", "")).strip():
            raise ConnectorError("key is required (object key in the bucket)")

    async def test_connection(
        self, config: dict[str, Any], secret: dict[str, Any] | None
    ) -> None:
        self.validate_config(config)
        try:
            await self._store.get_object(key=str(config["key"]))
        except Exception as exc:
            raise ConnectorError(f"object not readable: {type(exc).__name__}") from exc

    async def preview(
        self,
        config: dict[str, Any],
        secret: dict[str, Any] | None,
        *,
        target: str | None = None,
        limit: int = 50,
    ) -> PreviewResult:
        self.validate_config(config)
        capped = max(1, min(limit, _MAX_PREVIEW_ROWS))
        try:
            raw = await self._store.get_object(key=str(config["key"]))
            table = await asyncio.to_thread(_read_table, str(config["format"]), raw)
        except ConnectorError:
            raise
        except Exception as exc:
            raise ConnectorError(f"preview failed: {type(exc).__name__}") from exc
        sample = table.slice(0, capped)
        columns = list(sample.column_names)
        rows = [list(row.values()) for row in sample.to_pylist()]
        return PreviewResult(objects=[str(config["key"])], columns=columns, rows=rows)


def _read_table(fmt: str, raw: bytes) -> Any:  # noqa: ANN401 — pyarrow/pandas vary by format
    """Parse raw bytes into a pyarrow Table by format (runs in a worker thread)."""
    buf = io.BytesIO(raw)
    fmt = fmt.lower()
    if fmt == "csv":
        import pyarrow.csv as pa_csv

        return pa_csv.read_csv(buf)
    if fmt == "parquet":
        import pyarrow.parquet as pa_pq

        return pa_pq.read_table(buf)  # type: ignore[no-untyped-call]
    if fmt == "json":
        import pyarrow.json as pa_json

        return pa_json.read_json(buf)
    if fmt == "excel":
        import pandas as pd
        import pyarrow as pa

        return pa.Table.from_pandas(pd.read_excel(buf))
    raise ConnectorError(f"unsupported format {fmt!r}")
