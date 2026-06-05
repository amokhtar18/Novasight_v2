"""Derive a tenant's physical resource names from its slug.

This is the *one* place the naming convention lives. Provisioning (the seed
script, and later the tenant-create API) computes names here and persists them
in ``TenantResourceMap``; nothing else re-derives them. The prefixes below are a
naming convention that is identical in every environment, so they are constants
rather than configuration (config governs *where* infrastructure is, not how a
tenant's logical resources are named).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# A slug must be a safe identifier fragment: it ends up inside an Iceberg
# namespace, a ClickHouse database name, and a dbt schema name.
_SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{1,62}$")

# Prefix applied to the slug for the serving DB / transform schema so tenant
# resources never collide with system objects.
_RESOURCE_PREFIX = "tenant_"


@dataclass(frozen=True)
class TenantResources:
    """The three physical homes for a tenant's data."""

    iceberg_namespace: str
    clickhouse_db: str
    dbt_schema: str


def validate_slug(slug: str) -> str:
    """Return the slug if it is a safe identifier fragment, else raise."""
    if not _SLUG_RE.match(slug):
        raise ValueError(
            f"invalid tenant slug {slug!r}: must match {_SLUG_RE.pattern} "
            "(lowercase letter, then 1-62 of [a-z0-9_])"
        )
    return slug


def resources_for_slug(slug: str) -> TenantResources:
    """Compute the Iceberg namespace, ClickHouse DB, and dbt schema for a slug."""
    validate_slug(slug)
    return TenantResources(
        iceberg_namespace=slug,
        clickhouse_db=f"{_RESOURCE_PREFIX}{slug}",
        dbt_schema=f"{_RESOURCE_PREFIX}{slug}",
    )
