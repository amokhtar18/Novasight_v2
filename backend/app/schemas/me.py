"""Response schema for the /me endpoint.

``TenantContextRead`` mirrors the fields of ``TenantContext`` in a Pydantic
model so it can be serialised to JSON and validated by the router.  It contains
no secrets, no auth tokens, and no client-supplied data — all fields come from
the server-side resolved ``TenantContext``.
"""
from __future__ import annotations

from pydantic import BaseModel


class TenantContextRead(BaseModel):
    """The resolved tenant context returned to the authenticated caller.

    All fields are derived server-side from the JWT claim and the tenant
    registry — never from the request body.
    """

    tenant_id: str
    iceberg_namespace: str
    clickhouse_db: str
    dbt_schema: str


class MeRead(TenantContextRead):
    """Tenant context plus the verified caller identity (from the JWT).

    Lets the frontend render the signed-in user from a server-verified source
    instead of decoding the token client-side. ``roles`` drives which admin/
    superuser UI is shown — the backend remains the real authorization gate.
    """

    subject: str
    email: str
    tenant: str
    roles: list[str]
