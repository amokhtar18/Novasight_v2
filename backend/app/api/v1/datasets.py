"""Dataset endpoints — CSV upload and tenant-scoped listing.

Thin router: it resolves the tenant context and delegates all work to
``DatasetService``. The tenant scope comes from ``get_tenant_context`` (the
verified JWT), never from the request — there is no tenant id in any payload or
path here by design.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, UploadFile

from app.core.config import Settings, get_settings
from app.core.crypto import build_kms_provider
from app.core.security import Principal, get_principal
from app.core.sensitive import apply_to_rows, may_view_sensitive
from app.schemas.dataset import DatasetRead
from app.schemas.query import QueryRequest, QueryResponse
from app.services.clickhouse_datasets import (
    ClickHouseDatasetService,
    get_clickhouse_dataset_service,
)
from app.services.datasets import DatasetService, get_dataset_service
from app.tenancy.context import TenantContext, get_tenant_context

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.post("/upload", response_model=DatasetRead, status_code=201)
async def upload_dataset(
    file: UploadFile = File(...),  # noqa: B008
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    svc: DatasetService = Depends(get_dataset_service),  # noqa: B008
) -> DatasetRead:
    """Accept a CSV, store it under the tenant's prefix, and record the dataset."""
    dataset = await svc.upload(ctx, file)
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
    result = ch_svc.run_aggregation(ctx, dataset, request)

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
