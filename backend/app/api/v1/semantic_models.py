"""Semantic-model registry endpoints — the wizard's definitions (#8).

CRUD over a tenant's semantic-model definitions. On every change the service
regenerates the tenant's Cube model file (codegen is the single writer), so a saved
model becomes a governed cube queryable through the read-only ``/semantic`` path (#9).

Reads need only a tenant context. Mutations require the tenant **superuser** role —
defining the governed semantic layer writes to the shared Cube model volume and
affects every query in the tenant, so it is a power-user action (like ``/sources``).
The tenant is resolved from the JWT, never a body/path value.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response, status

from app.core.security import Principal, require_tenant_superuser
from app.models.semantic_model import SemanticModel
from app.schemas.semantic_model import (
    SemanticModelConfig,
    SemanticModelCreate,
    SemanticModelDefRead,
    SemanticModelUpdate,
)
from app.services.semantic_models import (
    SemanticModelService,
    get_semantic_model_service,
)
from app.tenancy.context import TenantContext, get_tenant_context

router = APIRouter(prefix="/semantic-models", tags=["semantic-models"])


def _to_read(model: SemanticModel) -> SemanticModelDefRead:
    return SemanticModelDefRead(
        id=model.id,
        name=model.name,
        base_table=model.base_table,
        config=SemanticModelConfig.model_validate(model.config),
        enabled=model.enabled,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


@router.get("", response_model=list[SemanticModelDefRead])
async def list_semantic_models(
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    svc: SemanticModelService = Depends(get_semantic_model_service),  # noqa: B008
) -> list[SemanticModelDefRead]:
    """List the tenant's semantic-model definitions."""
    return [_to_read(m) for m in await svc.list_for_tenant(ctx)]


@router.get("/{model_id}", response_model=SemanticModelDefRead)
async def get_semantic_model(
    model_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    svc: SemanticModelService = Depends(get_semantic_model_service),  # noqa: B008
) -> SemanticModelDefRead:
    """Fetch one semantic-model definition (404 if not in the caller's tenant)."""
    return _to_read(await svc.get_for_tenant(ctx, model_id))


@router.post("", response_model=SemanticModelDefRead, status_code=status.HTTP_201_CREATED)
async def create_semantic_model(
    payload: SemanticModelCreate,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    _: Principal = Depends(require_tenant_superuser),  # noqa: B008
    svc: SemanticModelService = Depends(get_semantic_model_service),  # noqa: B008
) -> SemanticModelDefRead:
    """Define a new semantic model (regenerates the tenant's Cube codegen)."""
    return _to_read(await svc.create(ctx, payload))


@router.patch("/{model_id}", response_model=SemanticModelDefRead)
async def update_semantic_model(
    model_id: uuid.UUID,
    payload: SemanticModelUpdate,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    _: Principal = Depends(require_tenant_superuser),  # noqa: B008
    svc: SemanticModelService = Depends(get_semantic_model_service),  # noqa: B008
) -> SemanticModelDefRead:
    """Update a semantic model (partial; regenerates the tenant's Cube codegen)."""
    return _to_read(await svc.update(ctx, model_id, payload))


@router.delete("/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_semantic_model(
    model_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    _: Principal = Depends(require_tenant_superuser),  # noqa: B008
    svc: SemanticModelService = Depends(get_semantic_model_service),  # noqa: B008
) -> Response:
    """Delete a semantic model (regenerates the tenant's Cube codegen)."""
    await svc.delete(ctx, model_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
