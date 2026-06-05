"""Health-check response schemas.

``HealthRead`` is the top-level response.  ``ComponentStatus`` describes the
result of a single dependency probe (Postgres, Redis, …).
"""
from __future__ import annotations

from pydantic import BaseModel


class ComponentStatus(BaseModel):
    """Status of a single infrastructure dependency."""

    name: str
    status: str  # "up" | "down"
    detail: str | None = None


class HealthRead(BaseModel):
    """Overall health-check response returned by ``GET /api/v1/health``."""

    status: str  # "healthy" | "degraded"
    components: list[ComponentStatus]
