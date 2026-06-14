"""dbt model + test registry: tenant-scoped CRUD + codegen regeneration (#5/#6).

Stores wizard-authored dbt models (and their data tests) and, on every change,
regenerates that tenant's dbt project subtree via the codegen (the single writer).
Model names are unique per tenant (a name is the dbt model name). Every query is
scoped to ``ctx.tenant_id``; a model from another tenant is 404.

Writing is skipped when no dbt models dir is configured (e.g. tests) — the definition
still persists and renders.
"""
from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.codegen import (
    DbtModelInput,
    DbtTestInput,
    write_tenant_dbt_models,
)
from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.models.dbt_model import DbtModel, DbtTest
from app.schemas.dbt_model import DbtModelCreate, DbtModelUpdate, DbtTestDef
from app.tenancy.context import TenantContext


class DbtModelService:
    """Manage a tenant's dbt model/test definitions and keep codegen in sync."""

    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self._db = db
        self._settings = settings

    async def list_for_tenant(self, ctx: TenantContext) -> list[DbtModel]:
        result = await self._db.execute(
            select(DbtModel)
            .where(DbtModel.tenant_id == uuid.UUID(ctx.tenant_id))
            .options(selectinload(DbtModel.tests))
            .order_by(DbtModel.name.asc())
        )
        return list(result.scalars().all())

    async def get_for_tenant(self, ctx: TenantContext, model_id: uuid.UUID) -> DbtModel:
        result = await self._db.execute(
            select(DbtModel)
            .where(
                DbtModel.id == model_id,
                DbtModel.tenant_id == uuid.UUID(ctx.tenant_id),
            )
            .options(selectinload(DbtModel.tests))
        )
        model = result.scalar_one_or_none()
        if model is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="dbt model not found")
        return model

    async def create(self, ctx: TenantContext, data: DbtModelCreate) -> DbtModel:
        await self._require_name_free(ctx, data.name)
        config = dict(data.config)
        if data.incremental is not None:
            config["incremental"] = data.incremental.model_dump(exclude_none=True)
        model = DbtModel(
            tenant_id=uuid.UUID(ctx.tenant_id),
            name=data.name,
            layer=data.layer,
            materialization=data.materialization,
            config=config,
            sql=data.sql,
            enabled=data.enabled,
            tests=[self._test_row(ctx, t) for t in data.tests],
        )
        self._db.add(model)
        await self._db.flush()
        await self._regenerate(ctx)
        return await self.get_for_tenant(ctx, model.id)

    async def update(
        self, ctx: TenantContext, model_id: uuid.UUID, data: DbtModelUpdate
    ) -> DbtModel:
        model = await self.get_for_tenant(ctx, model_id)
        if data.name is not None and data.name != model.name:
            await self._require_name_free(ctx, data.name)
            model.name = data.name
        if data.layer is not None:
            model.layer = data.layer
        if data.materialization is not None:
            model.materialization = data.materialization
        if data.sql is not None:
            model.sql = data.sql
        if data.config is not None:
            model.config = data.config
        if data.incremental is not None:
            # Merge the typed incremental settings over the (possibly just-set) config.
            model.config = {
                **(model.config or {}),
                "incremental": data.incremental.model_dump(exclude_none=True),
            }
        if data.enabled is not None:
            model.enabled = data.enabled
        if data.tests is not None:
            # Replace the full set of tests (cascade delete-orphan removes the old).
            model.tests = [self._test_row(ctx, t) for t in data.tests]
        await self._db.flush()
        await self._regenerate(ctx)
        return await self.get_for_tenant(ctx, model.id)

    async def delete(self, ctx: TenantContext, model_id: uuid.UUID) -> None:
        model = await self.get_for_tenant(ctx, model_id)
        await self._db.delete(model)
        await self._db.flush()
        await self._regenerate(ctx)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _test_row(self, ctx: TenantContext, t: DbtTestDef) -> DbtTest:
        return DbtTest(
            tenant_id=uuid.UUID(ctx.tenant_id),
            column_name=t.column_name,
            test_type=t.test_type,
            config=t.config,
        )

    async def _require_name_free(self, ctx: TenantContext, name: str) -> None:
        existing = await self._db.execute(
            select(DbtModel.id).where(
                DbtModel.tenant_id == uuid.UUID(ctx.tenant_id),
                DbtModel.name == name,
            )
        )
        if existing.first() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A dbt model named '{name}' already exists",
            )

    async def _regenerate(self, ctx: TenantContext) -> None:
        """Re-render this tenant's enabled models into its dbt project subtree."""
        models = await self.list_for_tenant(ctx)
        inputs = [
            DbtModelInput(
                name=m.name,
                materialization=m.materialization,
                sql=m.sql or "",
                unique_key=list((m.config or {}).get("incremental", {}).get("unique_key", [])),
                incremental_strategy=(m.config or {})
                .get("incremental", {})
                .get("incremental_strategy"),
                on_schema_change=(m.config or {})
                .get("incremental", {})
                .get("on_schema_change"),
                tests=[
                    DbtTestInput(
                        test_type=t.test_type, column_name=t.column_name, config=t.config
                    )
                    for t in m.tests
                ],
            )
            for m in models
            if m.enabled
        ]
        models_dir = self._settings.dbt.models_dir
        if models_dir:
            write_tenant_dbt_models(models_dir, ctx.dbt_schema, inputs)


def get_dbt_model_service(
    db: AsyncSession = Depends(get_db),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> DbtModelService:
    """FastAPI dependency: assemble a ``DbtModelService`` from request scope."""
    return DbtModelService(db=db, settings=settings)
