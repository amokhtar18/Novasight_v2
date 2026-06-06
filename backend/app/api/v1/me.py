"""Protected /me endpoint — demonstrates auth + tenant context resolution.

Two routes:

* ``GET /api/v1/me`` — returns the resolved ``TenantContext``.
* ``POST /api/v1/me`` — accepts an optional ``tenant_id`` in the request body
  (or as a query param) to prove it is **ignored**.  The response always
  reflects the token's tenant, never the body/query value.

This endpoint has no business logic beyond proving the invariant:
  - Requests without a valid token → 401 (from ``get_principal``).
  - Requests with a token for an unknown / suspended tenant → 403 (from
    ``get_tenant_context``).
  - A ``tenant_id`` supplied by the client is silently discarded; the response
    contains only the server-resolved context.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.security import Principal, get_principal
from app.schemas.me import MeRead, TenantContextRead
from app.tenancy.context import TenantContext, get_tenant_context

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=MeRead)
async def get_me(
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    principal: Principal = Depends(get_principal),  # noqa: B008
) -> MeRead:
    """Return the resolved tenant context and verified identity for the caller."""
    return MeRead(
        tenant_id=ctx.tenant_id,
        iceberg_namespace=ctx.iceberg_namespace,
        clickhouse_db=ctx.clickhouse_db,
        dbt_schema=ctx.dbt_schema,
        subject=principal.subject,
        email=principal.email,
        tenant=principal.tenant_key,
        roles=sorted(principal.roles),
    )


class _MePostBody(BaseModel):
    """Request body for ``POST /me`` — the optional ``tenant_id`` is ignored."""

    tenant_id: str | None = None   # client-supplied; intentionally discarded


@router.post("", response_model=TenantContextRead)
async def post_me(
    _body: _MePostBody = _MePostBody(),  # noqa: B008
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
) -> TenantContextRead:
    """Return the resolved tenant context; ``tenant_id`` in the body is ignored.

    This route exists solely to prove the body-tenant-ignored invariant required
    by the acceptance criteria: regardless of what the client sends in
    ``body.tenant_id``, the response is scoped to the token's tenant.
    """
    return TenantContextRead(
        tenant_id=ctx.tenant_id,
        iceberg_namespace=ctx.iceberg_namespace,
        clickhouse_db=ctx.clickhouse_db,
        dbt_schema=ctx.dbt_schema,
    )
