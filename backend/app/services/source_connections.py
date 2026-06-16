"""Source-connection business logic: tenant-scoped CRUD + credential encryption.

Secrets are stored only as an envelope-encrypted blob (``app.core.crypto``); they
are decrypted in-process solely to test/preview/run a source, and never returned to
clients. Every query is scoped to ``ctx.tenant_id`` (tenancy-isolation invariant);
a source owned by another tenant is indistinguishable from not-found (404).
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.crypto import EncryptionError, build_kms_provider, decrypt_value, encrypt_value
from app.core.db import get_db
from app.core.object_store import ObjectStore, get_object_store
from app.ingestion.connectors import (
    ConnectorError,
    IntrospectResult,
    PreviewResult,
    SourceConnector,
    build_connector,
)
from app.models.source_connection import SourceConnection
from app.schemas.source import SourceConnectionCreate, SourceConnectionUpdate
from app.tenancy.context import TenantContext


class SourceConnectionService:
    """Manage and probe a tenant's source connections."""

    def __init__(self, db: AsyncSession, store: ObjectStore, settings: Settings) -> None:
        self._db = db
        self._store = store
        self._settings = settings

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def list_for_tenant(self, ctx: TenantContext) -> list[SourceConnection]:
        result = await self._db.execute(
            select(SourceConnection)
            .where(SourceConnection.tenant_id == uuid.UUID(ctx.tenant_id))
            .order_by(SourceConnection.name.asc())
        )
        return list(result.scalars().all())

    async def get_for_tenant(self, ctx: TenantContext, source_id: uuid.UUID) -> SourceConnection:
        result = await self._db.execute(
            select(SourceConnection).where(
                SourceConnection.id == source_id,
                SourceConnection.tenant_id == uuid.UUID(ctx.tenant_id),
            )
        )
        source = result.scalar_one_or_none()
        if source is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
        return source

    async def create(self, ctx: TenantContext, data: SourceConnectionCreate) -> SourceConnection:
        self._validate_kind_config(data.kind, data.config)
        source = SourceConnection(
            tenant_id=uuid.UUID(ctx.tenant_id),
            name=data.name,
            kind=data.kind,
            config=data.config,
            secret_ciphertext=self._encrypt(data.secret),
        )
        self._db.add(source)
        await self._db.flush()
        await self._db.refresh(source)
        return source

    async def update(
        self, ctx: TenantContext, source_id: uuid.UUID, data: SourceConnectionUpdate
    ) -> SourceConnection:
        source = await self.get_for_tenant(ctx, source_id)
        if data.name is not None:
            source.name = data.name
        if data.config is not None:
            self._validate_kind_config(source.kind, data.config)
            source.config = data.config
        if data.status is not None:
            source.status = data.status
        if data.secret is not None:
            source.secret_ciphertext = self._encrypt(data.secret)
        await self._db.flush()
        await self._db.refresh(source)
        return source

    async def delete(self, ctx: TenantContext, source_id: uuid.UUID) -> None:
        source = await self.get_for_tenant(ctx, source_id)
        await self._db.delete(source)
        await self._db.flush()

    # ------------------------------------------------------------------
    # Probe
    # ------------------------------------------------------------------

    async def test(self, ctx: TenantContext, source_id: uuid.UUID) -> None:
        source = await self.get_for_tenant(ctx, source_id)
        connector = self._connector(source.kind)
        try:
            await connector.test_connection(source.config, self._decrypt(source.secret_ciphertext))
        except ConnectorError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    async def preview(
        self, ctx: TenantContext, source_id: uuid.UUID, *, target: str | None, limit: int
    ) -> PreviewResult:
        source = await self.get_for_tenant(ctx, source_id)
        connector = self._connector(source.kind)
        try:
            return await connector.preview(
                source.config,
                self._decrypt(source.secret_ciphertext),
                target=target,
                limit=limit,
            )
        except ConnectorError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    async def introspect(
        self,
        ctx: TenantContext,
        source_id: uuid.UUID,
        *,
        schema: str | None,
        table: str | None,
    ) -> IntrospectResult:
        source = await self.get_for_tenant(ctx, source_id)
        connector = self._connector(source.kind)
        try:
            return await connector.introspect(
                source.config,
                self._decrypt(source.secret_ciphertext),
                schema=schema,
                table=table,
            )
        except ConnectorError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _connector(self, kind: str) -> SourceConnector:
        try:
            return build_connector(kind, store=self._store)
        except ConnectorError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def _validate_kind_config(self, kind: str, config: dict[str, Any]) -> None:
        connector = self._connector(kind)
        try:
            connector.validate_config(config)
        except ConnectorError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def _encrypt(self, secret: dict[str, Any] | None) -> str | None:
        if not secret:
            return None
        try:
            provider = build_kms_provider(self._settings)
        except EncryptionError as exc:
            raise HTTPException(
                status_code=400,
                detail="Encryption is not configured; cannot store source credentials",
            ) from exc
        return encrypt_value(provider, json.dumps(secret))

    def _decrypt(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        provider = build_kms_provider(self._settings)
        result: dict[str, Any] = json.loads(decrypt_value(provider, token))
        return result


def get_source_connection_service(
    db: AsyncSession = Depends(get_db),  # noqa: B008
    store: ObjectStore = Depends(get_object_store),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> SourceConnectionService:
    """FastAPI dependency: assemble a ``SourceConnectionService`` from request scope."""
    return SourceConnectionService(db=db, store=store, settings=settings)
