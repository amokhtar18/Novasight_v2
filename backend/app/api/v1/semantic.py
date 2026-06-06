"""Semantic-layer endpoints — list governed models + run structured queries (#9).

The point-and-click analogue of the AI ``NL→chart`` path: the manual chart builder
lists governed models and resolves a structured measures/dimensions request through
the governed Cube semantic layer. Both are read-only and grounded; neither touches a
raw physical table (golden rule #3).

Reads require only a tenant context — these are governed, read-only queries any
authenticated tenant user may run (like ``/ai/query``). The tenant is resolved from
the JWT, never a body/path value.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.ai.semantic.client import CubeAuthError, CubeQueryError
from app.schemas.query import QueryResponse
from app.schemas.semantic import SemanticModelRead, SemanticQueryRequest
from app.services.semantic import (
    SemanticService,
    SemanticValidationError,
    get_semantic_service,
)
from app.tenancy.context import TenantContext, get_tenant_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/semantic", tags=["semantic"])


@router.get("/models", response_model=list[SemanticModelRead])
async def list_models(
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    svc: SemanticService = Depends(get_semantic_service),  # noqa: B008
) -> list[SemanticModelRead]:
    """List the governed semantic models the tenant may query."""
    try:
        return await svc.list_models(ctx)
    except CubeAuthError as exc:
        logger.warning("Semantic meta Cube auth error: tenant_id=%r", ctx.tenant_id)
        raise HTTPException(
            status_code=503,
            detail="Semantic layer is temporarily unavailable. Please try again.",
        ) from exc
    except CubeQueryError as exc:
        logger.error("Semantic meta Cube query error: tenant_id=%r", ctx.tenant_id)
        raise HTTPException(
            status_code=503,
            detail="Semantic layer returned an error. Please try again.",
        ) from exc


@router.post(
    "/query",
    response_model=QueryResponse,
    responses={
        422: {"description": "A measure/dimension is not in the governed allow-list"},
        503: {"description": "Semantic layer temporarily unavailable"},
    },
    summary="Run a structured, grounded query against the semantic layer",
    description=(
        "Resolve a structured measures/dimensions request through the governed Cube "
        "semantic layer, scoped to the caller's tenant. Every reference is validated "
        "against the tenant's governed meta before any query runs; an unknown "
        "reference returns 422. The result columns are ``dimensions + measures`` — the "
        "same shape the shared chart renderer consumes for AI charts."
    ),
)
async def query_semantic(
    payload: SemanticQueryRequest,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    svc: SemanticService = Depends(get_semantic_service),  # noqa: B008
) -> QueryResponse:
    """Resolve a grounded structured query and return aligned columns + rows."""
    try:
        return await svc.query(ctx, payload)
    except SemanticValidationError as exc:
        logger.info(
            "Semantic query rejected: tenant_id=%r reason=%r", ctx.tenant_id, exc.reason
        )
        raise HTTPException(status_code=422, detail=exc.reason) from exc
    except CubeAuthError as exc:
        logger.warning("Semantic query Cube auth error: tenant_id=%r", ctx.tenant_id)
        raise HTTPException(
            status_code=503,
            detail="Semantic layer is temporarily unavailable. Please try again.",
        ) from exc
    except CubeQueryError as exc:
        logger.error("Semantic query Cube query error: tenant_id=%r", ctx.tenant_id)
        raise HTTPException(
            status_code=503,
            detail="Semantic layer returned an error. Please try again.",
        ) from exc
