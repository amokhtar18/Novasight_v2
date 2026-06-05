"""Dataset upload + listing business logic.

The router is thin: it hands this service the resolved ``TenantContext`` and the
``UploadFile``. The service is the only place that:

* validates file type and size (size limit from settings — never a literal),
* derives the tenant-scoped object key from the context (never the client),
* writes the raw bytes to the object store, and
* records the ``Dataset`` row scoped to the tenant.

Every read path filters on ``ctx.tenant_id`` so one tenant can never see
another's datasets (see the ``tenancy-isolation`` skill).
"""
from __future__ import annotations

import re
import uuid

from fastapi import Depends, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.core.object_store import ObjectStore, get_object_store
from app.models.dataset import Dataset
from app.tenancy.context import TenantContext

# CSV is the feature this endpoint accepts — a fixed product constant, not an
# environment- or tenant-specific value, so it lives in code rather than config.
_CSV_EXTENSION = ".csv"
_DEFAULT_CSV_CONTENT_TYPE = "text/csv"

# Read the upload in 1 MiB chunks so we can enforce the size cap without ever
# buffering more than the limit allows.
_CHUNK_SIZE = 1024 * 1024
_BYTES_PER_MB = 1024 * 1024

# Keep object keys to a safe character set; the dataset id guarantees uniqueness,
# so this only needs to neutralise path traversal and odd characters.
_UNSAFE_KEY_CHARS = re.compile(r"[^A-Za-z0-9._-]")


class DatasetService:
    """Upload and list datasets for one tenant."""

    def __init__(
        self,
        db: AsyncSession,
        store: ObjectStore,
        settings: Settings,
    ) -> None:
        self._db = db
        self._store = store
        self._settings = settings

    async def upload(self, ctx: TenantContext, file: UploadFile) -> Dataset:
        """Validate, store, and record an uploaded CSV for the tenant in ``ctx``."""
        filename = (file.filename or "").strip()
        if not filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A filename is required",
            )
        if not filename.lower().endswith(_CSV_EXTENSION):
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Only .csv files are accepted",
            )

        body = await self._read_capped(file)
        if not body:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty",
            )

        dataset_id = uuid.uuid4()
        object_key = self._object_key(ctx, dataset_id, filename)
        content_type = file.content_type or _DEFAULT_CSV_CONTENT_TYPE

        # Store the bytes first; only record the row if the object landed.
        await self._store.put_object(
            key=object_key,
            body=body,
            content_type=content_type,
        )

        dataset = Dataset(
            id=dataset_id,
            tenant_id=uuid.UUID(ctx.tenant_id),
            name=filename,
            original_filename=filename,
            object_key=object_key,
            content_type=content_type,
            size_bytes=len(body),
        )
        self._db.add(dataset)
        await self._db.flush()
        # Load server-side defaults (created_at, status) onto the instance.
        await self._db.refresh(dataset)
        return dataset

    async def list_for_tenant(self, ctx: TenantContext) -> list[Dataset]:
        """Return the tenant's datasets, newest first. Scoped by ``ctx.tenant_id``."""
        result = await self._db.execute(
            select(Dataset)
            .where(Dataset.tenant_id == uuid.UUID(ctx.tenant_id))
            .order_by(Dataset.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_for_tenant(
        self, ctx: TenantContext, dataset_id: uuid.UUID
    ) -> Dataset:
        """Load one dataset by id, scoped to the tenant in ``ctx``.

        The query filters on ``tenant_id`` as well as the id, so a dataset owned by
        another tenant is indistinguishable from one that does not exist — both raise
        404, never leaking existence across tenants (see ``tenancy-isolation``).
        """
        result = await self._db.execute(
            select(Dataset).where(
                Dataset.id == dataset_id,
                Dataset.tenant_id == uuid.UUID(ctx.tenant_id),
            )
        )
        dataset = result.scalar_one_or_none()
        if dataset is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dataset not found",
            )
        return dataset

    async def _read_capped(self, file: UploadFile) -> bytes:
        """Read the upload, raising 413 if it exceeds the configured size cap."""
        max_bytes = self._settings.max_upload_mb * _BYTES_PER_MB
        chunks: list[bytes] = []
        total = 0
        while chunk := await file.read(_CHUNK_SIZE):
            total += len(chunk)
            if total > max_bytes:
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail=f"File exceeds the {self._settings.max_upload_mb} MB limit",
                )
            chunks.append(chunk)
        return b"".join(chunks)

    def _object_key(
        self, ctx: TenantContext, dataset_id: uuid.UUID, filename: str
    ) -> str:
        """Derive the tenant-prefixed raw object key.

        The tenant's object-store prefix is its Iceberg namespace (the two are
        the same isolation boundary per the architecture). The key is derived
        entirely from the server-side context and the new dataset id.
        """
        safe_name = _UNSAFE_KEY_CHARS.sub("_", filename)
        return f"{ctx.iceberg_namespace}/raw/datasets/{dataset_id}/{safe_name}"


def get_dataset_service(
    db: AsyncSession = Depends(get_db),  # noqa: B008
    store: ObjectStore = Depends(get_object_store),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> DatasetService:
    """FastAPI dependency: assemble a ``DatasetService`` from request scope."""
    return DatasetService(db=db, store=store, settings=settings)
