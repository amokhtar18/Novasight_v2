"""SQL database connector — pull from Postgres/MySQL/etc. via SQLAlchemy.

Config (non-secret): ``driver`` (a SQLAlchemy dialect, e.g. ``postgresql`` /
``mysql+pymysql`` / ``sqlite``), ``host``, ``port``, ``database``, ``username``,
and optional ``query`` (URL query params). Secret: ``password``.

Test connects and runs ``SELECT 1``; preview lists tables (via the inspector) and,
for a chosen table, returns a capped row sample. The blocking SQLAlchemy work runs
in a worker thread so the event loop is never blocked. The extract→Iceberg load
runs in the orchestration layer using the same URL builder.
"""
from __future__ import annotations

import asyncio
from typing import Any, ClassVar

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL, Engine

from app.ingestion.connectors.base import (
    ConnectorError,
    PreviewResult,
    SourceConnector,
)

# Hard cap so a preview can never pull an unbounded result set.
_MAX_PREVIEW_ROWS = 200
# Identifier guard for the optional preview target (table name) — defends the
# interpolated FROM clause, which cannot be parameterised.
_SAFE_IDENT = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.")


class SqlDatabaseConnector(SourceConnector):
    """Connector for any SQLAlchemy-supported relational database."""

    kind: ClassVar[str] = "sql_database"

    def validate_config(self, config: dict[str, Any]) -> None:
        driver = str(config.get("driver", "")).strip()
        if not driver:
            raise ConnectorError("driver is required (a SQLAlchemy dialect)")
        # sqlite needs only a database/path; networked engines need a host.
        if not driver.startswith("sqlite") and not str(config.get("host", "")).strip():
            raise ConnectorError("host is required for this driver")

    async def test_connection(
        self, config: dict[str, Any], secret: dict[str, Any] | None
    ) -> None:
        self.validate_config(config)
        await asyncio.to_thread(self._sync_test, config, secret)

    async def preview(
        self,
        config: dict[str, Any],
        secret: dict[str, Any] | None,
        *,
        target: str | None = None,
        limit: int = 50,
    ) -> PreviewResult:
        self.validate_config(config)
        return await asyncio.to_thread(self._sync_preview, config, secret, target, limit)

    async def extract(
        self,
        config: dict[str, Any],
        secret: dict[str, Any] | None,
        *,
        target: str,
    ) -> Any:  # noqa: ANN401 — pyarrow.Table
        self.validate_config(config)
        return await asyncio.to_thread(self._sync_extract, config, secret, target)

    # ------------------------------------------------------------------
    # Blocking implementations (run in a worker thread)
    # ------------------------------------------------------------------

    def _sync_test(self, config: dict[str, Any], secret: dict[str, Any] | None) -> None:
        engine = self._engine(config, secret)
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception as exc:
            raise ConnectorError(f"could not connect: {type(exc).__name__}") from exc
        finally:
            engine.dispose()

    def _sync_preview(
        self,
        config: dict[str, Any],
        secret: dict[str, Any] | None,
        target: str | None,
        limit: int,
    ) -> PreviewResult:
        capped = max(1, min(limit, _MAX_PREVIEW_ROWS))
        engine = self._engine(config, secret)
        try:
            with engine.connect() as conn:
                objects = sorted(inspect(conn).get_table_names())
                if target is None:
                    return PreviewResult(objects=objects)
                if target not in objects:
                    raise ConnectorError(f"unknown table {target!r}")
                if any(ch not in _SAFE_IDENT for ch in target):
                    raise ConnectorError("invalid table name")
                result = conn.execute(text(f"SELECT * FROM {target} LIMIT {capped}"))  # noqa: S608
                columns = list(result.keys())
                rows = [list(r) for r in result.fetchall()]
                return PreviewResult(objects=objects, columns=columns, rows=rows)
        except ConnectorError:
            raise
        except Exception as exc:
            raise ConnectorError(f"preview failed: {type(exc).__name__}") from exc
        finally:
            engine.dispose()

    def _sync_extract(
        self, config: dict[str, Any], secret: dict[str, Any] | None, target: str
    ) -> Any:  # noqa: ANN401 — pyarrow.Table
        import pyarrow as pa

        engine = self._engine(config, secret)
        try:
            with engine.connect() as conn:
                if target not in set(inspect(conn).get_table_names()):
                    raise ConnectorError(f"unknown table {target!r}")
                if any(ch not in _SAFE_IDENT for ch in target):
                    raise ConnectorError("invalid table name")
                result = conn.execute(text(f"SELECT * FROM {target}"))  # noqa: S608
                columns = list(result.keys())
                rows = result.fetchall()
                data = {col: [row[i] for row in rows] for i, col in enumerate(columns)}
                return pa.table(data)
        except ConnectorError:
            raise
        except Exception as exc:
            raise ConnectorError(f"extract failed: {type(exc).__name__}") from exc
        finally:
            engine.dispose()

    @staticmethod
    def _engine(config: dict[str, Any], secret: dict[str, Any] | None) -> Engine:
        url = URL.create(
            drivername=str(config["driver"]),
            username=config.get("username") or None,
            password=(secret or {}).get("password"),
            host=config.get("host") or None,
            port=int(config["port"]) if config.get("port") else None,
            database=config.get("database") or None,
            query=config.get("query") or {},
        )
        return create_engine(url, pool_pre_ping=True)
