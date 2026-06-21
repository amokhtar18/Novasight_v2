"""Serving-layer introspection: the tenant's ClickHouse marts + columns (#6).

Feeds the semantic wizard's table/column dropdowns. Reads are strictly tenant-scoped:
the database is always ``ctx.clickhouse_db`` (resolved server-side from the JWT), and
the queries hit ``system.tables`` / ``system.columns`` filtered to that database via
**bound parameters** — never string-interpolated. Everything runs read-only.

This is a UI helper, so it degrades gracefully: if the serving layer is cold or
unreachable, it returns an empty list (the wizard falls back to free-text) rather than
failing the request.
"""
from __future__ import annotations

import logging

from fastapi import Depends

from app.core.clickhouse import ClickHouseClient, get_clickhouse_client
from app.schemas.serving import ServingColumn
from app.tenancy.context import TenantContext

logger = logging.getLogger(__name__)


class ServingService:
    """List a tenant's ClickHouse serving tables and their columns (read-only)."""

    def __init__(self, ch: ClickHouseClient) -> None:
        self._ch = ch

    def list_tables(self, ctx: TenantContext) -> list[str]:
        """Serving table names in the tenant's database (marts + registered tables)."""
        try:
            result = self._ch.query(
                "SELECT name FROM system.tables "
                "WHERE database = {db:String} AND name NOT LIKE '.inner%' "
                "ORDER BY name",
                database=ctx.clickhouse_db,
                parameters={"db": ctx.clickhouse_db},
                read_only=True,
            )
        except Exception:  # graceful degradation for a UI helper
            logger.warning(
                "Serving table introspection failed: tenant_id=%r db=%r",
                ctx.tenant_id,
                ctx.clickhouse_db,
            )
            return []
        return [str(row[0]) for row in result.rows]

    def list_columns(self, ctx: TenantContext, table: str) -> list[ServingColumn]:
        """Columns (name + type) of one serving ``table`` in the tenant's database."""
        try:
            result = self._ch.query(
                "SELECT name, type FROM system.columns "
                "WHERE database = {db:String} AND table = {tbl:String} "
                "ORDER BY position",
                database=ctx.clickhouse_db,
                parameters={"db": ctx.clickhouse_db, "tbl": table},
                read_only=True,
            )
        except Exception:  # graceful degradation for a UI helper
            logger.warning(
                "Serving column introspection failed: tenant_id=%r db=%r table=%r",
                ctx.tenant_id,
                ctx.clickhouse_db,
                table,
            )
            return []
        return [ServingColumn(name=str(row[0]), type=str(row[1])) for row in result.rows]


def get_serving_service(
    ch: ClickHouseClient = Depends(get_clickhouse_client),  # noqa: B008
) -> ServingService:
    """FastAPI dependency: assemble a ``ServingService`` from request scope."""
    return ServingService(ch=ch)
