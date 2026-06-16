"""Connector framework — the seam between a source's *kind* and how we talk to it.

Each connector validates its config, tests connectivity, and previews available
objects/rows so the ETL wizard can show what a source offers before a pipeline is
built. Credentials arrive already-decrypted as a small ``secret`` dict (the service
layer owns encryption at rest via ``app.core.crypto``); a connector never persists
or logs them.

IO methods are async. Connectors that do blocking IO (e.g. SQLAlchemy) wrap it in a
worker thread so the event loop is never blocked; connectors over async resources
(the object store) await directly.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar


class ConnectorError(Exception):
    """A connector could not validate config, connect, or preview a source."""


@dataclass
class PreviewResult:
    """What a source offers: the selectable objects and an optional row sample."""

    # Names of selectable objects (DB tables, files) the user can pick from.
    objects: list[str] = field(default_factory=list)
    # Sample columns/rows when a specific target was previewed (else empty).
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)


@dataclass
class ColumnInfo:
    """One source column: its name and its source-side SQL type (as a string)."""

    name: str
    source_type: str


@dataclass
class IntrospectResult:
    """Staged schema introspection for the pipeline wizard (#5).

    Each call answers one level of the schema → table → column drill-down: with no
    ``schema``/``table`` it lists ``schemas``; with a ``schema`` it lists that schema's
    ``tables``; with a ``schema`` + ``table`` it lists that table's ``columns``.
    """

    schemas: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    columns: list[ColumnInfo] = field(default_factory=list)


class SourceConnector(ABC):
    """Base class for all source connectors. Subclasses set ``kind``."""

    kind: ClassVar[str]

    @abstractmethod
    def validate_config(self, config: dict[str, Any]) -> None:
        """Raise ``ConnectorError`` if ``config`` is missing/invalid for this kind."""

    @abstractmethod
    async def test_connection(
        self, config: dict[str, Any], secret: dict[str, Any] | None
    ) -> None:
        """Raise ``ConnectorError`` if the source cannot be reached with these creds."""

    @abstractmethod
    async def preview(
        self,
        config: dict[str, Any],
        secret: dict[str, Any] | None,
        *,
        target: str | None = None,
        limit: int = 50,
    ) -> PreviewResult:
        """List selectable objects; if ``target`` is given, also sample its rows."""

    @abstractmethod
    async def extract(
        self,
        config: dict[str, Any],
        secret: dict[str, Any] | None,
        *,
        target: str,
    ) -> Any:  # noqa: ANN401 — a pyarrow.Table (no type stubs); kept loose on purpose
        """Read the full selected ``target`` object/table into a pyarrow ``Table``.

        Unlike ``preview`` this is uncapped — it is the extract step of a pipeline
        run, executed off the request path (worker). Raises ``ConnectorError`` on
        failure. Blocking IO must run in a worker thread.
        """

    async def introspect(
        self,
        config: dict[str, Any],
        secret: dict[str, Any] | None,
        *,
        schema: str | None = None,
        table: str | None = None,
    ) -> IntrospectResult:
        """Drill schema → table → columns for the field-level pipeline wizard (#5).

        Default: not supported. Relational connectors override this; object-store
        connectors (e.g. filesystem) have no schemas, so they raise here.
        """
        raise ConnectorError(f"{self.kind} does not support schema introspection")
