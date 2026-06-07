"""Semantic-model registry: tenant-scoped CRUD over wizard definitions (#8).

Stores the user's model definitions and, on every change, regenerates that tenant's
Cube model file via the codegen (the single writer). Names are unique per tenant (a
model name becomes a Cube cube name). Every query is scoped to ``ctx.tenant_id``; a
model from another tenant is indistinguishable from not-found (404).

The generated file is isolation-gated on ``clickhouse_db`` (see ``app.codegen``), so a
tenant's cubes only compile for that tenant. Writing is skipped when no model dir is
configured (e.g. tests) — the definition still persists and renders.
"""
from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.codegen import CubeModelInput, render_tenant_models, write_tenant_models
from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.models.semantic_model import SemanticModel
from app.schemas.semantic_model import (
    SemanticModelConfig,
    SemanticModelCreate,
    SemanticModelUpdate,
)
from app.tenancy.context import TenantContext


class SemanticModelService:
    """Manage a tenant's semantic-model definitions and keep Cube codegen in sync."""

    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self._db = db
        self._settings = settings

    async def list_for_tenant(self, ctx: TenantContext) -> list[SemanticModel]:
        result = await self._db.execute(
            select(SemanticModel)
            .where(SemanticModel.tenant_id == uuid.UUID(ctx.tenant_id))
            .order_by(SemanticModel.name.asc())
        )
        return list(result.scalars().all())

    async def get_for_tenant(self, ctx: TenantContext, model_id: uuid.UUID) -> SemanticModel:
        result = await self._db.execute(
            select(SemanticModel).where(
                SemanticModel.id == model_id,
                SemanticModel.tenant_id == uuid.UUID(ctx.tenant_id),
            )
        )
        model = result.scalar_one_or_none()
        if model is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Semantic model not found"
            )
        return model

    async def create(self, ctx: TenantContext, data: SemanticModelCreate) -> SemanticModel:
        await self._require_name_free(ctx, data.name)
        model = SemanticModel(
            tenant_id=uuid.UUID(ctx.tenant_id),
            name=data.name,
            base_table=data.base_table,
            config=data.config.model_dump(),
            enabled=data.enabled,
        )
        self._db.add(model)
        await self._db.flush()
        await self._db.refresh(model)
        await self._regenerate(ctx)
        return model

    async def update(
        self, ctx: TenantContext, model_id: uuid.UUID, data: SemanticModelUpdate
    ) -> SemanticModel:
        model = await self.get_for_tenant(ctx, model_id)
        if data.name is not None and data.name != model.name:
            await self._require_name_free(ctx, data.name)
            model.name = data.name
        if data.base_table is not None:
            model.base_table = data.base_table
        if data.config is not None:
            model.config = data.config.model_dump()
        if data.enabled is not None:
            model.enabled = data.enabled
        await self._db.flush()
        await self._db.refresh(model)
        await self._regenerate(ctx)
        return model

    async def delete(self, ctx: TenantContext, model_id: uuid.UUID) -> None:
        model = await self.get_for_tenant(ctx, model_id)
        await self._db.delete(model)
        await self._db.flush()
        await self._regenerate(ctx)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _require_name_free(self, ctx: TenantContext, name: str) -> None:
        existing = await self._db.execute(
            select(SemanticModel.id).where(
                SemanticModel.tenant_id == uuid.UUID(ctx.tenant_id),
                SemanticModel.name == name,
            )
        )
        if existing.first() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A semantic model named '{name}' already exists",
            )

    async def _regenerate(self, ctx: TenantContext) -> None:
        """Re-render this tenant's enabled models into its Cube file (single writer)."""
        models = await self.list_for_tenant(ctx)
        inputs = [
            CubeModelInput(
                name=m.name,
                base_table=m.base_table,
                config=SemanticModelConfig.model_validate(m.config),
            )
            for m in models
            if m.enabled
        ]
        content = render_tenant_models(inputs)
        model_dir = self._settings.cube.model_dir
        if model_dir:
            write_tenant_models(model_dir, ctx.clickhouse_db, content)


def get_semantic_model_service(
    db: AsyncSession = Depends(get_db),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> SemanticModelService:
    """FastAPI dependency: assemble a ``SemanticModelService`` from request scope."""
    return SemanticModelService(db=db, settings=settings)
