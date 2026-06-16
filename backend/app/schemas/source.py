"""Schemas for source-connection management (the ETL wizard's source step).

Secrets are write-only: they are accepted on create/update and never returned —
reads expose only ``has_secret``. The non-secret ``config`` is returned as stored.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class EngineSpecRead(BaseModel):
    """A SQL engine the connection wizard offers (mirrors ``connectors.engines``).

    Drives the wizard's engine dropdown and its per-engine defaults: the standard
    ``default_port`` to prefill, whether the engine ``supports_schemas`` (so the
    pipeline wizard can offer a schema step), and how the "database" field reads
    (``database_label`` — a service name on Oracle). The SQLAlchemy drivername is
    intentionally *not* exposed; the backend resolves it from ``key``.
    """

    key: str
    label: str
    default_port: int
    supports_schemas: bool
    database_label: str


class SourceConnectionCreate(BaseModel):
    """Body for ``POST /sources``."""

    name: str = Field(..., min_length=1, max_length=255)
    kind: str = Field(..., min_length=1, max_length=64)
    config: dict[str, Any] = Field(default_factory=dict)
    # Credentials (e.g. {"password": "..."}); encrypted at rest. Omit when none.
    secret: dict[str, Any] | None = None


class SourceConnectionUpdate(BaseModel):
    """Body for ``PATCH /sources/{id}`` — partial; omit ``secret`` to keep it."""

    name: str | None = Field(default=None, max_length=255)
    config: dict[str, Any] | None = None
    secret: dict[str, Any] | None = None
    status: str | None = Field(default=None, max_length=32)


class SourceConnectionRead(BaseModel):
    """A source connection as returned to clients — never includes the secret."""

    id: str
    name: str
    kind: str
    config: dict[str, Any]
    status: str
    has_secret: bool


class SourceTestResponse(BaseModel):
    """Result of a connectivity test."""

    ok: bool
    detail: str | None = None


class SourcePreviewRequest(BaseModel):
    """Body for ``POST /sources/{id}/preview``."""

    target: str | None = Field(default=None, description="Table/object to sample.")
    limit: int = Field(default=50, ge=1, le=200)


class SourcePreviewResponse(BaseModel):
    """Selectable objects and an optional row sample."""

    objects: list[str]
    columns: list[str]
    rows: list[list[Any]]
