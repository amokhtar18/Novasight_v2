"""Source-connection endpoints (ETL wizard — source step).

Reads (list/get) require only a tenant context; mutations and probes (create,
update, delete, test, preview) require the tenant superuser role, since they
configure data-engineering plumbing and reach external systems. The tenant is
resolved from the JWT — never a body/path value.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response, status

from app.core.security import Principal, require_tenant_superuser
from app.ingestion.connectors import KINDS
from app.ingestion.connectors.engines import ENGINES
from app.ingestion.type_mapping import suggest_target_type
from app.models.source_connection import SourceConnection
from app.schemas.source import (
    EngineSpecRead,
    IntrospectColumn,
    SourceConnectionCreate,
    SourceConnectionRead,
    SourceConnectionUpdate,
    SourceIntrospectResponse,
    SourcePreviewRequest,
    SourcePreviewResponse,
    SourceTestResponse,
)
from app.services.source_connections import (
    SourceConnectionService,
    get_source_connection_service,
)
from app.tenancy.context import TenantContext, get_tenant_context

router = APIRouter(prefix="/sources", tags=["sources"])


def _to_read(source: SourceConnection) -> SourceConnectionRead:
    return SourceConnectionRead(
        id=str(source.id),
        name=source.name,
        kind=source.kind,
        config=source.config,
        status=source.status,
        has_secret=source.secret_ciphertext is not None,
    )


@router.get("/kinds", response_model=list[str])
async def list_kinds(
    _: TenantContext = Depends(get_tenant_context),  # noqa: B008
) -> list[str]:
    """Connector kinds the wizard offers."""
    return list(KINDS)


@router.get("/engines", response_model=list[EngineSpecRead])
async def list_engines(
    _: TenantContext = Depends(get_tenant_context),  # noqa: B008
) -> list[EngineSpecRead]:
    """SQL engines the connection wizard offers, with per-engine defaults."""
    return [
        EngineSpecRead(
            key=spec.key,
            label=spec.label,
            default_port=spec.default_port,
            supports_schemas=spec.supports_schemas,
            database_label=spec.database_label,
        )
        for spec in ENGINES.values()
    ]


@router.get("", response_model=list[SourceConnectionRead])
async def list_sources(
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    svc: SourceConnectionService = Depends(get_source_connection_service),  # noqa: B008
) -> list[SourceConnectionRead]:
    """List the tenant's source connections."""
    return [_to_read(s) for s in await svc.list_for_tenant(ctx)]


@router.get("/{source_id}", response_model=SourceConnectionRead)
async def get_source(
    source_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    svc: SourceConnectionService = Depends(get_source_connection_service),  # noqa: B008
) -> SourceConnectionRead:
    """Fetch one source connection (404 if not in the caller's tenant)."""
    return _to_read(await svc.get_for_tenant(ctx, source_id))


@router.post("", response_model=SourceConnectionRead, status_code=status.HTTP_201_CREATED)
async def create_source(
    payload: SourceConnectionCreate,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    _: Principal = Depends(require_tenant_superuser),  # noqa: B008
    svc: SourceConnectionService = Depends(get_source_connection_service),  # noqa: B008
) -> SourceConnectionRead:
    """Create a source connection (credentials encrypted at rest)."""
    return _to_read(await svc.create(ctx, payload))


@router.patch("/{source_id}", response_model=SourceConnectionRead)
async def update_source(
    source_id: uuid.UUID,
    payload: SourceConnectionUpdate,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    _: Principal = Depends(require_tenant_superuser),  # noqa: B008
    svc: SourceConnectionService = Depends(get_source_connection_service),  # noqa: B008
) -> SourceConnectionRead:
    """Update a source connection (partial; omit ``secret`` to keep it)."""
    return _to_read(await svc.update(ctx, source_id, payload))


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    source_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    _: Principal = Depends(require_tenant_superuser),  # noqa: B008
    svc: SourceConnectionService = Depends(get_source_connection_service),  # noqa: B008
) -> Response:
    """Delete a source connection."""
    await svc.delete(ctx, source_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{source_id}/test", response_model=SourceTestResponse)
async def test_source(
    source_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    _: Principal = Depends(require_tenant_superuser),  # noqa: B008
    svc: SourceConnectionService = Depends(get_source_connection_service),  # noqa: B008
) -> SourceTestResponse:
    """Test connectivity to a source (raises 422 with a safe reason on failure)."""
    await svc.test(ctx, source_id)
    return SourceTestResponse(ok=True)


@router.post("/{source_id}/preview", response_model=SourcePreviewResponse)
async def preview_source(
    source_id: uuid.UUID,
    payload: SourcePreviewRequest,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    _: Principal = Depends(require_tenant_superuser),  # noqa: B008
    svc: SourceConnectionService = Depends(get_source_connection_service),  # noqa: B008
) -> SourcePreviewResponse:
    """List a source's selectable objects and, for a target, a row sample."""
    result = await svc.preview(ctx, source_id, target=payload.target, limit=payload.limit)
    return SourcePreviewResponse(
        objects=result.objects, columns=result.columns, rows=result.rows
    )


@router.post("/{source_id}/introspect", response_model=SourceIntrospectResponse)
async def introspect_source(
    source_id: uuid.UUID,
    schema: str | None = None,
    table: str | None = None,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    _: Principal = Depends(require_tenant_superuser),  # noqa: B008
    svc: SourceConnectionService = Depends(get_source_connection_service),  # noqa: B008
) -> SourceIntrospectResponse:
    """Drill schema → table → columns for the field-level pipeline wizard (#5).

    One level per call (``schema``/``table`` are query params): none → schemas; a
    ``schema`` → its tables; ``schema`` + ``table`` → its columns, each tagged with a
    suggested destination type. Tenant superuser only (it reaches the source DB).
    """
    result = await svc.introspect(ctx, source_id, schema=schema, table=table)
    return SourceIntrospectResponse(
        schemas=result.schemas,
        tables=result.tables,
        columns=[
            IntrospectColumn(
                name=c.name,
                source_type=c.source_type,
                suggested_target_type=suggest_target_type(c.source_type),
            )
            for c in result.columns
        ],
    )
