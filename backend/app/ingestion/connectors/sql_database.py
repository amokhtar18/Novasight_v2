"""SQL database connector — pull from Postgres/MySQL/SQL Server/Oracle via SQLAlchemy.

Config (non-secret): ``engine`` (a key in the engine registry, e.g. ``postgres`` /
``mysql`` / ``sqlserver`` / ``oracle``) which resolves the SQLAlchemy ``drivername``,
or a raw ``driver`` override for engines not in the registry (e.g. ``sqlite``); plus
``host``, ``port``, ``database``, ``username``, and optional ``query`` (URL query
params). Secret: ``password``. See ``engines.py`` for the registry.

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
    ColumnInfo,
    ConnectorError,
    ExtractSpec,
    IntrospectResult,
    PreviewResult,
    SourceConnector,
)
from app.ingestion.connectors.engines import ENGINES, query_for, resolve_drivername

# Hard cap so a preview can never pull an unbounded result set.
_MAX_PREVIEW_ROWS = 200
# Identifier guard for the optional preview target (table name) — defends the
# interpolated FROM clause, which cannot be parameterised.
_SAFE_IDENT = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.")


class SqlDatabaseConnector(SourceConnector):
    """Connector for any SQLAlchemy-supported relational database."""

    kind: ClassVar[str] = "sql_database"

    def validate_config(self, config: dict[str, Any]) -> None:
        drivername = resolve_drivername(config)
        if not drivername:
            raise ConnectorError("engine (or a driver override) is required")
        # sqlite needs only a database/path; networked engines need a host.
        if not drivername.startswith("sqlite") and not str(config.get("host", "")).strip():
            raise ConnectorError("host is required for this engine")

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
        spec: ExtractSpec | None = None,
    ) -> Any:  # noqa: ANN401 — pyarrow.Table
        self.validate_config(config)
        return await asyncio.to_thread(self._sync_extract, config, secret, target, spec)

    async def introspect(
        self,
        config: dict[str, Any],
        secret: dict[str, Any] | None,
        *,
        schema: str | None = None,
        table: str | None = None,
    ) -> IntrospectResult:
        self.validate_config(config)
        return await asyncio.to_thread(self._sync_introspect, config, secret, schema, table)

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
        self,
        config: dict[str, Any],
        secret: dict[str, Any] | None,
        target: str,
        spec: ExtractSpec | None,
    ) -> Any:  # noqa: ANN401 — pyarrow.Table
        import pyarrow as pa

        if any(ch not in _SAFE_IDENT for ch in target):
            raise ConnectorError("invalid table name")
        engine = self._engine(config, secret)
        try:
            with engine.connect() as conn:
                schema = spec.schema if spec else None
                if target not in set(inspect(conn).get_table_names(schema=schema)):
                    raise ConnectorError(f"unknown table {target!r}")
                sql, params = self._build_extract_query(engine, target, spec)
                result = conn.execute(text(sql), params)
                source_cols = list(result.keys())
                rows = result.fetchall()
                # Rename to target names when a column map was given (else as-is).
                out_cols = self._rename(source_cols, spec)
                data = {out_cols[i]: [row[i] for row in rows] for i in range(len(source_cols))}
                return pa.table(data)
        except ConnectorError:
            raise
        except Exception as exc:
            raise ConnectorError(f"extract failed: {type(exc).__name__}") from exc
        finally:
            engine.dispose()

    @staticmethod
    def _rename(source_cols: list[str], spec: ExtractSpec | None) -> list[str]:
        if not spec or not spec.columns:
            return source_cols
        mapping = {c.source_name: c.target_name for c in spec.columns}
        return [mapping.get(c, c) for c in source_cols]

    @staticmethod
    def _build_extract_query(
        engine: Engine, target: str, spec: ExtractSpec | None
    ) -> tuple[str, dict[str, Any]]:
        """Build the extract SELECT + bound params from an ``ExtractSpec``.

        Identifiers (table, schema, columns) are quoted via the dialect's preparer;
        filter/CDC values are **bound parameters**, never interpolated — so a stored
        filter can't inject SQL. Empty ``columns`` → ``SELECT *``; no filters → no WHERE.
        """
        quote = engine.dialect.identifier_preparer.quote
        params: dict[str, Any] = {}
        if not spec:
            return f"SELECT * FROM {quote(target)}", params  # noqa: S608 — identifier quoted

        cols = ", ".join(quote(c.source_name) for c in spec.columns) if spec.columns else "*"
        from_sql = f"{quote(spec.schema)}.{quote(target)}" if spec.schema else quote(target)
        where: list[str] = []
        ops = {"eq": "=", "ne": "<>", "gt": ">", "ge": ">=", "lt": "<", "le": "<=", "like": "LIKE"}
        for i, f in enumerate(spec.filters):
            col = quote(f.column)
            if f.operator in ("is_null", "is_not_null"):
                where.append(f"{col} IS {'NOT ' if f.operator == 'is_not_null' else ''}NULL")
            elif f.operator == "in":
                values = f.value if isinstance(f.value, list) else []
                keys = []
                for j, v in enumerate(values):
                    k = f"f{i}_{j}"
                    params[k] = v
                    keys.append(f":{k}")
                where.append(f"{col} IN ({', '.join(keys)})" if keys else "1 = 0")
            elif f.operator in ops:
                params[f"f{i}"] = f.value
                where.append(f"{col} {ops[f.operator]} :f{i}")
        if spec.cdc_column and spec.cdc_since is not None:
            params["cdc_since"] = spec.cdc_since
            where.append(f"{quote(spec.cdc_column)} > :cdc_since")
        sql = f"SELECT {cols} FROM {from_sql}"  # noqa: S608 — identifiers quoted, values bound
        if where:
            sql += " WHERE " + " AND ".join(where)
        return sql, params

    def _sync_introspect(
        self,
        config: dict[str, Any],
        secret: dict[str, Any] | None,
        schema: str | None,
        table: str | None,
    ) -> IntrospectResult:
        # Guard the optional schema/table identifiers before they reach the
        # inspector (they are interpolated into reflection queries by the driver).
        for ident in (schema, table):
            if ident is not None and any(ch not in _SAFE_IDENT for ch in ident):
                raise ConnectorError("invalid schema/table name")
        engine = self._engine(config, secret)
        try:
            with engine.connect() as conn:
                inspector = inspect(conn)
                if table is not None:
                    # Columns of one table (schema may be None → default schema).
                    cols = inspector.get_columns(table, schema=schema)
                    columns = [
                        ColumnInfo(name=str(c["name"]), source_type=str(c["type"]))
                        for c in cols
                    ]
                    return IntrospectResult(columns=columns)
                if schema is not None:
                    return IntrospectResult(
                        tables=sorted(inspector.get_table_names(schema=schema))
                    )
                return IntrospectResult(schemas=sorted(inspector.get_schema_names()))
        except ConnectorError:
            raise
        except Exception as exc:
            raise ConnectorError(f"introspection failed: {type(exc).__name__}") from exc
        finally:
            engine.dispose()

    @staticmethod
    def _build_url(config: dict[str, Any], secret: dict[str, Any] | None) -> URL:
        """Build the SQLAlchemy URL from a connection config (pure; no DBAPI import).

        Split out from ``_engine`` so URL construction (drivername resolution, the
        registry's default port, query params) is unit-testable without the driver
        for that engine being installed — ``create_engine`` imports the DBAPI eagerly.
        """
        drivername = resolve_drivername(config)
        if not drivername:
            raise ConnectorError("engine (or a driver override) is required")
        # Port: explicit wins, else the registry's standard port for the engine.
        spec = ENGINES.get(str(config.get("engine", "")).strip())
        port = config.get("port") or (spec.default_port if spec else None)
        # Registry query params first, then any caller-supplied overrides.
        query = {**query_for(config), **(config.get("query") or {})}
        return URL.create(
            drivername=drivername,
            username=config.get("username") or None,
            password=(secret or {}).get("password"),
            host=config.get("host") or None,
            port=int(port) if port else None,
            database=config.get("database") or None,
            query=query,
        )

    @staticmethod
    def _engine(config: dict[str, Any], secret: dict[str, Any] | None) -> Engine:
        return create_engine(
            SqlDatabaseConnector._build_url(config, secret), pool_pre_ping=True
        )
