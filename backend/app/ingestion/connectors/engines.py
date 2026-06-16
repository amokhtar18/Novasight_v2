"""SQL engine registry — per-engine connection conventions for the wizard (#3/#4).

The ``sql_database`` connector is dialect-agnostic: it builds a SQLAlchemy URL and
talks to whatever the ``drivername`` points at. This registry names the engines we
ship support for and the *protocol* conventions each one uses — the SQLAlchemy
``drivername``, the standard listening port, and how the "database" field reads for
that engine (a service name on Oracle, a database on the rest).

These are protocol constants (PostgreSQL listens on 5432, Oracle on 1521), not
environment- or tenant-specific configuration — golden rule 1 is about the latter.
A deployment never overrides them; a *connection* supplies its own host/port/creds
through ``SourceConnection.config`` + the encrypted secret. Adding an engine is one
entry here plus its driver in ``pyproject.toml`` — no schema change (``engine`` is a
plain string in the connection config).

The drivers (all pure-Python / thin, so the backend image needs no system packages):
``psycopg2`` (Postgres), ``pymysql`` (MySQL), ``pymssql`` (SQL Server, no ODBC),
``oracledb`` thin mode (Oracle, no Instant Client).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EngineSpec:
    """Connection conventions for one SQL engine the wizard offers."""

    key: str               # stable id stored in SourceConnection.config["engine"]
    label: str             # human label for the wizard dropdown
    drivername: str        # SQLAlchemy dialect+driver, e.g. "postgresql+psycopg2"
    default_port: int      # standard listening port, prefilled in the wizard
    # Whether the engine has schemas distinct from the database (Postgres/MSSQL/
    # Oracle: yes; MySQL: a "schema" *is* a database, so we surface databases).
    supports_schemas: bool = True
    # How the connection's "database" field reads for this engine (a service name
    # on Oracle); shown as the field label/hint in the wizard.
    database_label: str = "Database"
    # Extra SQLAlchemy URL query params baked in for this driver (none by default).
    default_query: dict[str, str] = field(default_factory=dict)


# The engines we ship, in wizard display order. Keyed by ``key``.
ENGINES: dict[str, EngineSpec] = {
    "postgres": EngineSpec(
        key="postgres",
        label="PostgreSQL",
        drivername="postgresql+psycopg2",
        default_port=5432,
    ),
    "mysql": EngineSpec(
        key="mysql",
        label="MySQL",
        drivername="mysql+pymysql",
        default_port=3306,
        supports_schemas=False,  # a MySQL "schema" is a database
    ),
    "sqlserver": EngineSpec(
        key="sqlserver",
        label="SQL Server",
        drivername="mssql+pymssql",
        default_port=1433,
    ),
    "oracle": EngineSpec(
        key="oracle",
        label="Oracle",
        drivername="oracle+oracledb",
        default_port=1521,
        # In the URL the "database" segment is the Easy Connect service name.
        database_label="Service name",
    ),
}


def resolve_drivername(config: dict[str, object]) -> str | None:
    """Resolve the SQLAlchemy drivername for a connection config.

    Prefers the registry (``config["engine"]``); falls back to an explicit
    ``config["driver"]`` for back-compat / engines not in the registry. Returns
    ``None`` when neither is set (the connector treats that as a validation error).
    """
    engine = str(config.get("engine", "")).strip()
    if engine and engine in ENGINES:
        return ENGINES[engine].drivername
    driver = str(config.get("driver", "")).strip()
    return driver or None


def query_for(config: dict[str, object]) -> dict[str, str]:
    """The default URL query params for a config's engine (empty if none/unknown)."""
    engine = str(config.get("engine", "")).strip()
    spec = ENGINES.get(engine)
    return dict(spec.default_query) if spec else {}
