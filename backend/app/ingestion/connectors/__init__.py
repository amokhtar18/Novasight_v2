"""Connector registry — resolve a source ``kind`` to a connector instance.

The factory injects the dependencies a connector needs (the object store for the
filesystem connector); SQL needs none. Adding a connector is a new module + one
branch here — no config or schema migration (the ``kind`` is a plain string).
"""
from __future__ import annotations

from app.core.object_store import ObjectStore
from app.ingestion.connectors.base import (
    ColumnInfo,
    ConnectorError,
    IntrospectResult,
    PreviewResult,
    SourceConnector,
)
from app.ingestion.connectors.filesystem import FilesystemConnector
from app.ingestion.connectors.sql_database import SqlDatabaseConnector

# Kinds the ETL wizard offers.
KINDS: tuple[str, ...] = (SqlDatabaseConnector.kind, FilesystemConnector.kind)


def build_connector(kind: str, *, store: ObjectStore) -> SourceConnector:
    """Return a connector for ``kind`` or raise ``ConnectorError`` if unknown."""
    if kind == SqlDatabaseConnector.kind:
        return SqlDatabaseConnector()
    if kind == FilesystemConnector.kind:
        return FilesystemConnector(store)
    raise ConnectorError(f"unknown connector kind {kind!r}")


__all__ = [
    "KINDS",
    "ColumnInfo",
    "ConnectorError",
    "FilesystemConnector",
    "IntrospectResult",
    "PreviewResult",
    "SourceConnector",
    "SqlDatabaseConnector",
    "build_connector",
]
