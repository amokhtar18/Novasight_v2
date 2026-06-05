"""AI endpoints — NL→SQL (Task 4.3) and NL→Chart (Task 4.4).

Thin router: validates requests via Pydantic, delegates all work to the
service layer.  The tenant scope is resolved by ``get_tenant_context`` from
the authenticated JWT — never from the request body.

## Security-critical guarantees (enforced in the service/validator layers)

- LLM only sees governed semantic-layer objects (no raw physical tables).
- Generated SQL / chart specs are parsed and validated before any data is
  fetched (read-only, allow-list, tenant-db isolation, grounding allow-list).
- Read-only is enforced at both the validation layer AND the ClickHouse
  connection level (defense in depth).
- No tenant data crosses into another tenant's prompt or result.
- On ANY validation failure: FAIL CLOSED — return 422 with a safe message;
  NEVER execute/resolve unvalidated output.
- Raw LLM provider errors and API keys are never leaked to the client.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.ai.gateway.provider import LLMProviderError
from app.ai.nl_chart import (
    ChartValidationError,
    NLToChartService,
    get_nl_to_chart_service,
)
from app.ai.nl_sql import NLToSQLService, SQLValidationError, get_nl_to_sql_service
from app.ai.semantic.client import CubeAuthError, CubeQueryError
from app.schemas.chart import ChartSpec
from app.schemas.query import QueryResponse
from app.tenancy.context import TenantContext, get_tenant_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class NLQueryRequest(BaseModel):
    """Request body for POST /ai/query.

    Attributes:
        question: The natural-language question to answer from the semantic layer.
            Must be non-empty; the service rejects empty or whitespace-only strings.
    """

    question: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Natural-language question to translate to SQL and execute.",
    )


class NLQueryResponse(BaseModel):
    """Response for POST /ai/query on success.

    Attributes:
        sql: The validated SQL that was executed.  Returned for transparency
            (the caller can show it in the UI).  It is always the
            post-validation, post-row-cap form — never the raw LLM output.
        columns: Ordered list of column names in the result.
        rows: Result rows; each row is a list of values aligned with columns.
        row_count: Number of rows returned.
    """

    sql: str = Field(description="Validated SQL that was executed.")
    columns: list[str] = Field(description="Column names in result order.")
    rows: list[list[Any]] = Field(description="Result rows.")
    row_count: int = Field(description="Number of rows returned.")


class NLQueryError(BaseModel):
    """Structured error body for POST /ai/query on validation or generation failure.

    Attributes:
        detail: Human-readable reason (safe to display to the user).
        code: Machine-readable error code.
    """

    detail: str
    code: str


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/query",
    response_model=NLQueryResponse,
    status_code=200,
    responses={
        422: {"model": NLQueryError, "description": "SQL generation or validation failed"},
        503: {"description": "Semantic layer or LLM provider unavailable"},
    },
    summary="NL→SQL: translate a question to SQL and execute it",
    description=(
        "Ground the semantic layer for the current tenant, generate a SQL query via "
        "the LLM, validate it (read-only, allow-list, tenant isolation), then execute "
        "it read-only against the tenant's ClickHouse database.\n\n"
        "On any validation failure the endpoint returns 422 with a safe message. "
        "The raw LLM output is never returned or executed if validation fails."
    ),
)
async def nl_query(
    payload: NLQueryRequest,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    svc: NLToSQLService = Depends(get_nl_to_sql_service),  # noqa: B008
) -> NLQueryResponse:
    """Translate a natural-language question to SQL and execute it.

    The tenant context is resolved from the authenticated JWT — the caller
    cannot supply or influence the tenant scope.

    Fail-closed contract:
    - Validation failure (wrong statement type, disallowed table, cross-tenant
      DB qualifier, parse error, UNSATISFIABLE sentinel) → 422.
    - Semantic layer unavailable (Cube 403) → 503 with a safe message.
    - LLM provider error → 503 with a safe message; key never leaked.
    """
    try:
        validated_sql, result = await svc.query(ctx, question=payload.question)
    except SQLValidationError as exc:
        logger.info(
            "NL→SQL validation rejected: tenant_id=%r reason=%r",
            ctx.tenant_id,
            exc.reason,
        )
        # Raise HTTPException so FastAPI returns 422 with our safe message.
        raise HTTPException(
            status_code=422,
            detail=exc.reason,
        ) from exc
    except CubeAuthError as exc:
        logger.warning(
            "NL→SQL Cube auth error: tenant_id=%r status=%d",
            ctx.tenant_id,
            exc.status,
        )
        raise HTTPException(
            status_code=503,
            detail="Semantic layer is temporarily unavailable. Please try again.",
        ) from exc
    except CubeQueryError as exc:
        logger.error(
            "NL→SQL Cube query error: tenant_id=%r status=%d",
            ctx.tenant_id,
            exc.status,
        )
        raise HTTPException(
            status_code=503,
            detail="Semantic layer returned an error. Please try again.",
        ) from exc
    except LLMProviderError as exc:
        # NEVER leak the raw provider error (it may reference the model / key).
        logger.error(
            "NL→SQL LLM provider error: tenant_id=%r provider=%r status=%r",
            ctx.tenant_id,
            exc.provider,
            exc.status_code,
        )
        raise HTTPException(
            status_code=503,
            detail="AI provider is temporarily unavailable. Please try again.",
        ) from exc

    return NLQueryResponse(
        sql=validated_sql,
        columns=result.column_names,
        rows=[list(row) for row in result.rows],
        row_count=len(result.rows),
    )


# ---------------------------------------------------------------------------
# NL→Chart: request / response schemas
# ---------------------------------------------------------------------------


class NLChartRequest(BaseModel):
    """Request body for POST /ai/chart.

    Attributes:
        request: The natural-language chart request.  Must be non-empty.
    """

    request: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Natural-language description of the chart to generate.",
    )


class NLChartResponse(BaseModel):
    """Response for POST /ai/chart on success.

    The ``spec`` is a fully validated ``ChartSpec`` (version, type, query,
    encoding, options) using the same schema as the manual chart builder —
    the frontend ``ChartRenderer`` can consume it directly without any
    transformation.

    The ``data`` is a ``QueryResponse`` whose ``columns`` are exactly
    ``[encoding.x] + [s.field for s in encoding.series]``, so the renderer
    can map columns to visual channels by name.

    Attributes:
        spec: Validated chart specification (shared schema with the manual builder).
        data: Resolved data with columns aligned to the spec encoding.
    """

    spec: ChartSpec = Field(description="Validated chart specification.")
    data: QueryResponse = Field(description="Resolved query data aligned to the spec encoding.")


class NLChartError(BaseModel):
    """Structured error body for POST /ai/chart on validation or generation failure.

    Attributes:
        detail: Human-readable reason (safe to display to the user).
        code: Machine-readable error code.
    """

    detail: str
    code: str


# ---------------------------------------------------------------------------
# NL→Chart endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/chart",
    response_model=NLChartResponse,
    status_code=200,
    responses={
        422: {
            "model": NLChartError,
            "description": "Chart spec generation or validation failed",
        },
        503: {"description": "Semantic layer or LLM provider unavailable"},
    },
    summary="NL→Chart: translate a natural-language request into a validated chart spec + data",
    description=(
        "Ground the semantic layer for the current tenant, generate a ChartSpec via the "
        "LLM (using only governed metric_refs), validate it strictly (extra fields "
        "forbidden, grounding allow-list), then resolve the chart data via the semantic "
        "layer and return a {spec, data} pair.\n\n"
        "The spec is the same schema as the manual chart builder — the existing "
        "ChartRenderer can consume it directly.\n\n"
        "On any validation failure the endpoint returns 422 with a safe message. "
        "The raw LLM output is never returned or used if validation fails."
    ),
)
async def nl_chart(
    payload: NLChartRequest,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    svc: NLToChartService = Depends(get_nl_to_chart_service),  # noqa: B008
) -> NLChartResponse:
    """Translate a natural-language chart request into a validated spec + data.

    The tenant context is resolved from the authenticated JWT — the caller
    cannot supply or influence the tenant scope.

    Fail-closed contract:
    - Validation failure (UNSATISFIABLE, JSON parse error, schema violation,
      extra fields, ungrounded metric/dimension, missing metric_refs, inline
      query) → 422 with a safe, user-friendly message.
    - Semantic layer unavailable (Cube 403) → 503 with a safe message.
    - LLM provider error → 503 with a safe message; key never leaked.
    """
    try:
        spec, data = await svc.generate(ctx, request=payload.request)
    except ChartValidationError as exc:
        logger.info(
            "NL->Chart validation rejected: tenant_id=%r reason=%r",
            ctx.tenant_id,
            exc.reason,
        )
        raise HTTPException(
            status_code=422,
            detail=exc.reason,
        ) from exc
    except CubeAuthError as exc:
        logger.warning(
            "NL->Chart Cube auth error: tenant_id=%r status=%d",
            ctx.tenant_id,
            exc.status,
        )
        raise HTTPException(
            status_code=503,
            detail="Semantic layer is temporarily unavailable. Please try again.",
        ) from exc
    except CubeQueryError as exc:
        logger.error(
            "NL->Chart Cube query error: tenant_id=%r status=%d",
            ctx.tenant_id,
            exc.status,
        )
        raise HTTPException(
            status_code=503,
            detail="Semantic layer returned an error. Please try again.",
        ) from exc
    except LLMProviderError as exc:
        logger.error(
            "NL->Chart LLM provider error: tenant_id=%r provider=%r status=%r",
            ctx.tenant_id,
            exc.provider,
            exc.status_code,
        )
        raise HTTPException(
            status_code=503,
            detail="AI provider is temporarily unavailable. Please try again.",
        ) from exc

    return NLChartResponse(spec=spec, data=data)
