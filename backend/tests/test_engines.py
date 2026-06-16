"""Unit tests for the SQL engine registry + connector URL building (#3).

Covers the registry contents, drivername resolution (engine key vs raw ``driver``
override), validation, and that the connector builds a SQLAlchemy URL with the
registry's drivername + default port. URL building is exercised against Postgres
(psycopg2 is installed); the other engines' driver imports are lazy, so only their
drivername mapping is asserted here (no engine is constructed for them).
"""
from __future__ import annotations

import pytest

from app.ingestion.connectors.base import ConnectorError
from app.ingestion.connectors.engines import ENGINES, resolve_drivername
from app.ingestion.connectors.sql_database import SqlDatabaseConnector


def test_registry_has_the_four_engines() -> None:
    assert set(ENGINES) == {"postgres", "mysql", "sqlserver", "oracle"}
    assert ENGINES["oracle"].default_port == 1521
    assert ENGINES["oracle"].database_label == "Service name"
    assert ENGINES["mysql"].supports_schemas is False


@pytest.mark.parametrize(
    ("engine", "drivername"),
    [
        ("postgres", "postgresql+psycopg2"),
        ("mysql", "mysql+pymysql"),
        ("sqlserver", "mssql+pymssql"),
        ("oracle", "oracle+oracledb"),
    ],
)
def test_resolve_drivername_from_engine(engine: str, drivername: str) -> None:
    assert resolve_drivername({"engine": engine}) == drivername


def test_resolve_drivername_override_and_missing() -> None:
    # A raw ``driver`` override (e.g. sqlite, not in the registry) still works.
    assert resolve_drivername({"driver": "sqlite"}) == "sqlite"
    # Unknown engine falls through to the driver; neither set → None.
    assert resolve_drivername({"engine": "nope", "driver": "sqlite"}) == "sqlite"
    assert resolve_drivername({}) is None


def test_validate_config_requires_engine_and_host() -> None:
    conn = SqlDatabaseConnector()
    with pytest.raises(ConnectorError):
        conn.validate_config({})  # neither engine nor driver
    with pytest.raises(ConnectorError):
        conn.validate_config({"engine": "postgres"})  # networked engine needs a host


@pytest.mark.parametrize(
    ("engine", "drivername", "default_port"),
    [
        ("postgres", "postgresql+psycopg2", 5432),
        ("mysql", "mysql+pymysql", 3306),
        ("sqlserver", "mssql+pymssql", 1433),
        ("oracle", "oracle+oracledb", 1521),
    ],
)
def test_build_url_resolves_drivername_and_default_port(
    engine: str, drivername: str, default_port: int
) -> None:
    # _build_url is pure (no DBAPI import), so every engine is testable here even
    # without its driver installed in this dev venv.
    url = SqlDatabaseConnector._build_url(
        {"engine": engine, "host": "db", "database": "sales", "username": "ro"},
        {"password": "secret"},
    )
    assert url.drivername == drivername
    assert url.port == default_port  # registry default — no explicit port given
    assert url.host == "db"
    assert url.database == "sales"


def test_build_url_explicit_port_overrides_default() -> None:
    url = SqlDatabaseConnector._build_url(
        {"engine": "postgres", "host": "db", "port": 6432, "database": "sales"}, None
    )
    assert url.port == 6432
