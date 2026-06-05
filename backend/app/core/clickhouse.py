"""ClickHouse client seam — the serving-tier query boundary.

This is the one adapter the backend uses to run DDL and read-only queries against
ClickHouse (the per-tenant serving database, see ``docs/ARCHITECTURE.md``).
Everything that varies between environments — host, port, credentials — comes from
``ClickHouseSettings``; callers never see connection parameters (golden rule: no
hardcoded infrastructure).

## Tenant isolation at the connection level

``query()`` **requires** a ``database`` argument and opens the connection bound to
exactly that database. The calling service always derives it from the resolved
``TenantContext`` (never the client), so a query physically cannot resolve an
unqualified table outside the tenant's own ClickHouse database. ``command()`` takes
an *optional* database because the very first DDL step — ``CREATE DATABASE`` — must
run before the tenant database exists.

## Read-only by default

``query()`` runs with ClickHouse's ``readonly=1`` session setting unless a caller
explicitly opts out, so AI- and user-driven reads can never mutate serving data.

The ``ClickHouseClient`` Protocol is what services depend on, so tests substitute
an in-memory fake via ``dependency_overrides`` — no live ClickHouse needed.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import clickhouse_connect
from fastapi import Depends

from app.core.config import ClickHouseSettings, Settings, get_settings


@dataclass(frozen=True)
class QueryResult:
    """A read-only query result: ordered column names + row tuples."""

    column_names: list[str]
    rows: list[tuple[Any, ...]]

    def as_dicts(self) -> list[dict[str, Any]]:
        """Return rows as column-keyed dicts (convenience for serialization)."""
        return [dict(zip(self.column_names, row, strict=True)) for row in self.rows]


class ClickHouseClient(Protocol):
    """The minimal ClickHouse surface the backend depends on."""

    def command(self, sql: str, *, database: str | None = None) -> None:
        """Execute a statement that returns no rows (DDL, INSERT-as-SELECT).

        ``database`` binds the session to a database when given; pass ``None`` for
        cluster-level statements such as ``CREATE DATABASE``.
        """
        ...

    def query(
        self,
        sql: str,
        *,
        database: str,
        parameters: Mapping[str, Any] | None = None,
        read_only: bool = True,
    ) -> QueryResult:
        """Run ``sql`` bound to ``database`` and return the result.

        ``database`` is mandatory: the connection is opened against it, so
        unqualified table references resolve only inside that tenant database.
        """
        ...


class ConnectClickHouseClient:
    """``ClickHouseClient`` backed by ``clickhouse-connect`` over HTTP.

    A fresh client is opened per operation and bound to the requested database;
    clickhouse-connect clients are cheap HTTP sessions and binding the database at
    connection time is what makes tenant scoping airtight. All connection
    parameters come from ``ClickHouseSettings``.
    """

    # ClickHouse session setting name that forbids writes for the connection.
    _READONLY_SETTING = "readonly"

    def __init__(self, cfg: ClickHouseSettings) -> None:
        self._cfg = cfg

    def _connect(
        self, *, database: str | None, read_only: bool
    ) -> Any:  # noqa: ANN401 — clickhouse-connect client type is opaque
        settings: dict[str, Any] = {}
        if read_only:
            settings[self._READONLY_SETTING] = 1
        return clickhouse_connect.get_client(
            host=self._cfg.host,
            port=self._cfg.port,
            username=self._cfg.user,
            password=self._cfg.password.get_secret_value(),
            database=database,
            settings=settings,
        )

    def command(self, sql: str, *, database: str | None = None) -> None:
        # DDL/writes are never read-only.
        client = self._connect(database=database, read_only=False)
        try:
            client.command(sql)
        finally:
            client.close()

    def query(
        self,
        sql: str,
        *,
        database: str,
        parameters: Mapping[str, Any] | None = None,
        read_only: bool = True,
    ) -> QueryResult:
        client = self._connect(database=database, read_only=read_only)
        try:
            result = client.query(sql, parameters=dict(parameters) if parameters else None)
            column_names: Sequence[str] = result.column_names
            rows: Sequence[Sequence[Any]] = result.result_rows
            return QueryResult(
                column_names=list(column_names),
                rows=[tuple(row) for row in rows],
            )
        finally:
            client.close()


# Process-wide singleton; connection config is identical for every request and a
# fresh per-operation client is opened from it.
_client: ConnectClickHouseClient | None = None


def get_clickhouse_client(
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> ClickHouseClient:
    """FastAPI dependency: return the shared ClickHouse client built from settings.

    Overridden in tests with an in-memory fake via ``dependency_overrides``.
    """
    global _client
    if _client is None:
        _client = ConnectClickHouseClient(settings.clickhouse)
    return _client
