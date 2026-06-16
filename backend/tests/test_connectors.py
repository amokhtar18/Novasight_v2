"""Unit tests for the ETL connectors (no API, no live infra).

The SQL connector is exercised against a temporary SQLite file (a real
SQLAlchemy engine); the filesystem connector against a fake async object store.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.ingestion.connectors import build_connector
from app.ingestion.connectors.base import (
    ColumnSelect,
    ConnectorError,
    ExtractSpec,
    FilterSpec,
)

# ---------------------------------------------------------------------------
# SQL database connector
# ---------------------------------------------------------------------------


def _sqlite_db(tmp_path: Path) -> str:
    db = tmp_path / "src.db"
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE orders (id INTEGER, region TEXT)"))
        conn.execute(text("INSERT INTO orders VALUES (1, 'west'), (2, 'east')"))
    engine.dispose()
    return str(db)


@pytest.mark.asyncio
async def test_sql_connector_test_and_preview(tmp_path: Path) -> None:
    conn = build_connector("sql_database", store=None)  # type: ignore[arg-type]
    config = {"driver": "sqlite", "database": _sqlite_db(tmp_path)}

    await conn.test_connection(config, None)  # no raise

    listing = await conn.preview(config, None)
    assert "orders" in listing.objects
    assert listing.rows == []  # no target → just the object list

    sample = await conn.preview(config, None, target="orders", limit=10)
    assert sample.columns == ["id", "region"]
    assert len(sample.rows) == 2


@pytest.mark.asyncio
async def test_sql_connector_bad_config() -> None:
    conn = build_connector("sql_database", store=None)  # type: ignore[arg-type]
    with pytest.raises(ConnectorError):
        conn.validate_config({})  # missing driver


@pytest.mark.asyncio
async def test_sql_connector_unknown_table_is_error(tmp_path: Path) -> None:
    conn = build_connector("sql_database", store=None)  # type: ignore[arg-type]
    config = {"driver": "sqlite", "database": _sqlite_db(tmp_path)}
    with pytest.raises(ConnectorError):
        await conn.preview(config, None, target="ghost")


@pytest.mark.asyncio
async def test_sql_connector_introspect_drilldown(tmp_path: Path) -> None:
    conn = build_connector("sql_database", store=None)  # type: ignore[arg-type]
    config = {"driver": "sqlite", "database": _sqlite_db(tmp_path)}

    schemas = await conn.introspect(config, None)
    assert "main" in schemas.schemas  # sqlite's default schema

    tables = await conn.introspect(config, None, schema="main")
    assert "orders" in tables.tables

    cols = await conn.introspect(config, None, schema="main", table="orders")
    assert [c.name for c in cols.columns] == ["id", "region"]
    assert all(c.source_type for c in cols.columns)  # a type string was captured


@pytest.mark.asyncio
async def test_sql_connector_introspect_rejects_bad_identifier(tmp_path: Path) -> None:
    conn = build_connector("sql_database", store=None)  # type: ignore[arg-type]
    config = {"driver": "sqlite", "database": _sqlite_db(tmp_path)}
    with pytest.raises(ConnectorError):
        await conn.introspect(config, None, schema="main; drop table orders")


@pytest.mark.asyncio
async def test_sql_connector_extract_full(tmp_path: Path) -> None:
    conn = build_connector("sql_database", store=None)  # type: ignore[arg-type]
    config = {"driver": "sqlite", "database": _sqlite_db(tmp_path)}
    table = await conn.extract(config, None, target="orders")
    assert table.column_names == ["id", "region"]
    assert table.num_rows == 2


@pytest.mark.asyncio
async def test_sql_connector_extract_selects_renames_and_filters(tmp_path: Path) -> None:
    conn = build_connector("sql_database", store=None)  # type: ignore[arg-type]
    config = {"driver": "sqlite", "database": _sqlite_db(tmp_path)}
    spec = ExtractSpec(
        columns=[ColumnSelect(source_name="region", target_name="area")],
        filters=[FilterSpec(column="region", operator="eq", value="west")],
    )
    table = await conn.extract(config, None, target="orders", spec=spec)
    # Only the selected column, renamed, and only the matching row.
    assert table.column_names == ["area"]
    assert table.to_pydict() == {"area": ["west"]}


@pytest.mark.asyncio
async def test_sql_connector_extract_cdc_predicate(tmp_path: Path) -> None:
    conn = build_connector("sql_database", store=None)  # type: ignore[arg-type]
    config = {"driver": "sqlite", "database": _sqlite_db(tmp_path)}
    # id is the CDC column; only rows with id > 1 are returned (incremental run).
    spec = ExtractSpec(cdc_column="id", cdc_since=1)
    table = await conn.extract(config, None, target="orders", spec=spec)
    assert table.num_rows == 1
    assert table.to_pydict()["id"] == [2]


@pytest.mark.asyncio
async def test_sql_connector_extract_filter_value_is_bound_not_injected(tmp_path: Path) -> None:
    conn = build_connector("sql_database", store=None)  # type: ignore[arg-type]
    config = {"driver": "sqlite", "database": _sqlite_db(tmp_path)}
    # A SQL-injection attempt in the *value* is bound as a parameter → matches no row,
    # and certainly does not drop the table.
    spec = ExtractSpec(
        filters=[FilterSpec(column="region", operator="eq", value="west'; DROP TABLE orders;--")]
    )
    table = await conn.extract(config, None, target="orders", spec=spec)
    assert table.num_rows == 0
    # The table still exists and still has its two rows.
    assert (await conn.extract(config, None, target="orders")).num_rows == 2


# ---------------------------------------------------------------------------
# Filesystem connector
# ---------------------------------------------------------------------------


class _FakeStore:
    def __init__(self, data: dict[str, bytes]) -> None:
        self._data = data

    async def get_object(self, *, key: str) -> bytes:
        if key not in self._data:
            raise FileNotFoundError(key)
        return self._data[key]


@pytest.mark.asyncio
async def test_filesystem_connector_csv_preview() -> None:
    store = _FakeStore({"raw/data.csv": b"region,amount\nwest,10\neast,20\n"})
    conn = build_connector("filesystem", store=store)  # type: ignore[arg-type]
    config = {"format": "csv", "key": "raw/data.csv"}

    await conn.test_connection(config, None)  # readable
    result = await conn.preview(config, None, limit=5)
    assert result.columns == ["region", "amount"]
    assert result.rows[0] == ["west", 10]


@pytest.mark.asyncio
async def test_filesystem_connector_missing_object() -> None:
    store = _FakeStore({})
    conn = build_connector("filesystem", store=store)  # type: ignore[arg-type]
    with pytest.raises(ConnectorError):
        await conn.test_connection({"format": "csv", "key": "nope.csv"}, None)


@pytest.mark.asyncio
async def test_filesystem_connector_introspect_unsupported() -> None:
    store = _FakeStore({})
    conn = build_connector("filesystem", store=store)  # type: ignore[arg-type]
    with pytest.raises(ConnectorError):
        await conn.introspect({"format": "csv", "key": "x"}, None)


def test_unknown_kind() -> None:
    with pytest.raises(ConnectorError):
        build_connector("kafka", store=None)  # type: ignore[arg-type]
