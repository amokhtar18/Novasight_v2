"""Request/response models for tenant-scoped user management.

Users are always created and listed within the caller's own tenant (resolved from
the JWT, never the body). Passwords are write-only — they are never returned.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class UserRead(BaseModel):
    """A user as returned to clients — no password material."""

    id: str
    email: str
    name: str | None
    roles: list[str]
    is_active: bool


class UserCreate(BaseModel):
    """Body for ``POST /users`` — create a user in the caller's tenant."""

    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=8, max_length=128)
    name: str | None = Field(default=None, max_length=255)
    roles: list[str] = Field(default_factory=list)


class UserUpdate(BaseModel):
    """Body for ``PATCH /users/{id}`` — all fields optional (partial update)."""

    name: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    roles: list[str] | None = None
    is_active: bool | None = None
