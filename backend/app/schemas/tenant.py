"""Request/response models for control-plane tenant provisioning (Task 6.3)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class TenantProvisionRequest(BaseModel):
    """Body for ``POST /api/v1/tenants``.

    ``slug`` is validated as a safe identifier fragment by the provisioner
    (``app.tenancy.resources.validate_slug``) before any resource is created.
    """

    slug: str = Field(min_length=2, max_length=63, examples=["acme"])
    name: str = Field(min_length=1, max_length=255, examples=["Acme Corp"])
    admin_email: str = Field(min_length=3, max_length=320, examples=["admin@acme.example"])


class TenantRead(BaseModel):
    """The provisioned tenant and its physical resource coordinates."""

    id: str
    slug: str
    name: str
    status: str
    iceberg_namespace: str
    clickhouse_db: str
    dbt_schema: str
