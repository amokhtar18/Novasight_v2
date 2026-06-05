"""Response schema for dataset resources.

``DatasetRead`` is the safe, serialisable view of a ``Dataset`` ORM row returned
to the authenticated caller. It deliberately omits the internal ``object_key``
and ``tenant_id`` — those are server-side plumbing, not client concerns.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DatasetRead(BaseModel):
    """A dataset as returned to the client. Built from the ORM row."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    original_filename: str
    content_type: str
    size_bytes: int
    status: str
    created_at: datetime
