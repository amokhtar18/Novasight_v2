"""Dataset endpoints — CSV upload + materialization, tenant-scoped listing and query.

Thin router: it resolves the tenant context and delegates all work to the services
(``DatasetService`` for the control-plane row, ``CsvIcebergPipeline`` +
``ClickHouseDatasetService`` for the data-plane materialization). The tenant scope comes
from ``get_tenant_context`` (the verified JWT), never from the request — there is no
tenant id in any payload or path here by design.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from clickhouse_connect.driver.exceptions import DatabaseError
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.core.config import Settings, get_settings
from app.core.crypto import build_kms_provider
from app.core.object_store import ObjectStore, get_object_store
from app.core.security import Principal, get_principal
from app.core.sensitive import apply_to_rows, may_view_sensitive
from app.ingestion.csv_iceberg import CsvIcebergPipeline
from app.schemas.dataset import DatasetRead
from app.schemas.query import QueryRequest, QueryResponse
from app.services.clickhouse_datasets import (
    ClickHouseDatasetService,
    get_clickhouse_dataset_service,
)
from app.services.datasets import DatasetService, get_dataset_service
from app.tenancy.context import TenantContext, get_tenant_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/datasets", tags=["datasets"])

# Dataset lifecycle: "uploaded" (row recorded) -> "ingested" (materialized into the
# tenant's Iceberg + ClickHouse, queryable) or "failed" (materialization errored).
# Only an "ingested" dataset can be queried.
_STATUS_INGESTED = "ingested"
_STATUS_FAILED = "failed"

# ClickHouse error-code markers for "the dataset's database/table isn't there" — mapped
# to a clear 409 instead of a 500 (e.g. a dataset uploaded before materialization existed).
_CH_MISSING_MARKERS = ("UNKNOWN_DATABASE", "UNKNOWN_TABLE")


@router.post("/upload", response_model=DatasetRead, status_code=201)
async def upload_dataset(
    file: UploadFile = File(...),  # noqa: B008
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    svc: DatasetService = Depends(get_dataset_service),  # noqa: B008
    store: ObjectStore = Depends(get_object_store),  # noqa: B008
    ch_svc: ClickHouseDatasetService = Depends(get_clickhouse_dataset_service),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> DatasetRead:
    """Accept a CSV, store it under the tenant's prefix, then materialize it for querying.

    Materialization is the same chain that runs in the cloud, resolved entirely from the
    tenant context:

    1. ``CsvIcebergPipeline`` loads the raw CSV into an Iceberg table in the tenant's
       namespace (creating the namespace if needed).
    2. ``register_dataset`` exposes that Iceberg table as an ``IcebergS3``-engine table in
       the tenant's ClickHouse database (creating the database if needed).

    On success the dataset is marked ``ingested`` and is immediately queryable. If
    materialization fails the dataset is marked ``failed`` and a 502 is returned; the raw
    object and the dataset row are preserved so the failure is visible and re-uploadable.
    """
    dataset = await svc.upload(ctx, file)
    try:
        pipeline = CsvIcebergPipeline(ctx=ctx, store=store, settings=settings)
        await pipeline.run(dataset)
        # register_dataset is blocking (ClickHouse DDL + catalog I/O) — offload it so the
        # event loop is not stalled for the duration of the upload request.
        await asyncio.to_thread(ch_svc.register_dataset, ctx, dataset)
    except Exception as exc:
        logger.exception("Materialization failed for dataset %s", dataset.id)
        await svc.update_status(dataset, _STATUS_FAILED)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Dataset was stored but could not be ingested for querying.",
        ) from exc

    await svc.update_status(dataset, _STATUS_INGESTED)
    return DatasetRead.model_validate(dataset)


@router.get("", response_model=list[DatasetRead])
async def list_datasets(
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    svc: DatasetService = Depends(get_dataset_service),  # noqa: B008
) -> list[DatasetRead]:
    """List the authenticated tenant's datasets only."""
    datasets = await svc.list_for_tenant(ctx)
    return [DatasetRead.model_validate(d) for d in datasets]


@router.post("/{dataset_id}/query", response_model=QueryResponse)
async def query_dataset(
    dataset_id: uuid.UUID,
    request: QueryRequest,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    principal: Principal = Depends(get_principal),  # noqa: B008
    svc: DatasetService = Depends(get_dataset_service),  # noqa: B008
    ch_svc: ClickHouseDatasetService = Depends(get_clickhouse_dataset_service),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> QueryResponse:
    """Run a safe, read-only aggregation over one of the tenant's datasets.

    The dataset is loaded scoped to the tenant (404 if it is not theirs), then the
    structured request is compiled into a parameterised, row-capped ``SELECT`` that
    runs bound to the tenant's ClickHouse database. The ``dataset_id`` in the path is
    only ever resolved within the tenant scope — it can never reach another tenant's
    data.

    Sensitive columns come back encrypted from the lake; they are decrypted only for
    a principal holding the configured ``sensitive_view_role`` and masked otherwise.
    """
    dataset = await svc.get_for_tenant(ctx, dataset_id)
    if dataset.status != _STATUS_INGESTED:
        # Not yet materialized (e.g. still "uploaded", or "failed") — there is no
        # ClickHouse table to query. Surface a clear 409 rather than a 500.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Dataset is not ready to query yet (ingestion incomplete).",
        )
    try:
        result = ch_svc.run_aggregation(ctx, dataset, request)
    except DatabaseError as exc:
        # Defence in depth: a dataset marked ingested whose database/table is missing
        # (e.g. uploaded before materialization existed) maps to 409, not an opaque 500.
        if any(marker in str(exc) for marker in _CH_MISSING_MARKERS):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Dataset is not registered for querying. Re-upload it to ingest.",
            ) from exc
        raise

    sensitive = set(dataset.sensitive_columns or [])
    if sensitive:
        reveal = may_view_sensitive(principal, settings)
        provider = build_kms_provider(settings) if reveal else None
        rows = apply_to_rows(
            result.column_names, result.rows, sensitive, reveal=reveal, provider=provider
        )
    else:
        rows = [list(row) for row in result.rows]

    return QueryResponse(
        columns=result.column_names,
        rows=rows,
        row_count=len(rows),
    )
