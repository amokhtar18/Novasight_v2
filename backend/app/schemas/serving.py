"""Schemas for serving-layer (ClickHouse) introspection (#6 foundation).

The semantic wizard needs to offer real dropdowns of the tenant's serving tables
(dbt marts) and their columns. These are thin read models over ClickHouse
``system.tables`` / ``system.columns``, always scoped to the tenant database.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ServingColumn(BaseModel):
    """One column of a serving table."""

    name: str = Field(description="Column name.")
    type: str = Field(description="ClickHouse column type (e.g. 'String', 'Float64').")
