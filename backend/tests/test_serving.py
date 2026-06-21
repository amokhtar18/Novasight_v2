"""Serving introspection service tests (#6) — fake ClickHouse client, no infra."""
from __future__ import annotations

from typing import Any

from app.core.clickhouse import QueryResult
from app.services.serving import ServingService
from app.tenancy.context import TenantContext

_CTX = TenantContext(
    tenant_id="t1", iceberg_namespace="ns", clickhouse_db="tenant_db", dbt_schema="sch"
)


class _FakeCH:
    def __init__(self, *, raises: bool = False) -> None:
        self.raises = raises
        self.calls: list[dict[str, Any]] = []

    def query(
        self, sql: str, *, database: str, parameters: dict[str, Any], read_only: bool
    ) -> QueryResult:
        self.calls.append(
            {"sql": sql, "database": database, "parameters": parameters, "read_only": read_only}
        )
        if self.raises:
            raise RuntimeError("clickhouse down")
        if "system.tables" in sql:
            return QueryResult(column_names=["name"], rows=[("mart_orders",), ("mart_sales",)])
        return QueryResult(
            column_names=["name", "type"], rows=[("region", "String"), ("amount", "Float64")]
        )


def test_list_tables_is_tenant_scoped_and_read_only() -> None:
    ch = _FakeCH()
    svc = ServingService(ch=ch)  # type: ignore[arg-type]
    assert svc.list_tables(_CTX) == ["mart_orders", "mart_sales"]
    call = ch.calls[0]
    assert call["database"] == "tenant_db"
    assert call["parameters"] == {"db": "tenant_db"}
    assert call["read_only"] is True


def test_list_columns_binds_table_param() -> None:
    ch = _FakeCH()
    svc = ServingService(ch=ch)  # type: ignore[arg-type]
    cols = svc.list_columns(_CTX, "mart_sales")
    assert [(c.name, c.type) for c in cols] == [("region", "String"), ("amount", "Float64")]
    # The table is a bound parameter, never interpolated into the SQL text.
    assert ch.calls[0]["parameters"] == {"db": "tenant_db", "tbl": "mart_sales"}
    assert "mart_sales" not in ch.calls[0]["sql"]


def test_degrades_gracefully_on_clickhouse_error() -> None:
    svc = ServingService(ch=_FakeCH(raises=True))  # type: ignore[arg-type]
    assert svc.list_tables(_CTX) == []
    assert svc.list_columns(_CTX, "mart_sales") == []
