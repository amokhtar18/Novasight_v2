"""AI endpoints — NL→SQL (Task 4.3), NL→Chart (Task 4.4), insights & suggestions (Task 4.5).

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
- Insight summaries: the no-invented-numbers guardrail is enforced; any
  number in the summary not traceable to the result set triggers a 422.
- Suggestions: dataset ownership is verified server-side before profiling;
  only columns present in the profiled schema may appear in suggestions.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.ai.chat import ChatService, get_chat_service
from app.ai.gateway.provider import LLMProviderError
from app.ai.insights import (
    InsightGuardrailError,
    InsightService,
    SuggestionsService,
    get_insight_service,
    get_suggestions_service,
)
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


# ---------------------------------------------------------------------------
# Insight summaries (Task 4.5a): request / response schemas
# ---------------------------------------------------------------------------


# Hard cap on rows accepted by /ai/insights. A request larger than this is
# rejected at deserialisation (422) before any work — a safe-everywhere bound
# that prevents an oversized payload from tying up the event loop. The summary
# only ever sees a small preview of the result set anyway.
_MAX_INSIGHT_ROWS = 10_000


class InsightRequest(BaseModel):
    """Request body for POST /ai/insights.

    The caller supplies an already-computed result set (columns + rows) — the
    same shape as ``QueryResponse``.  The endpoint does NOT re-query data; it
    generates a summary from the provided values only.

    Attributes:
        columns: Ordered column names in the result set.
        rows: Data rows (each row is a list of values aligned with columns).
        context_hint: Optional free-text context (e.g. the dashboard title or
            the original question that produced the result set).  Used to
            orient the summary; never used to re-query data.
    """

    columns: list[str] = Field(
        ...,
        min_length=1,
        description="Ordered column names in the result set.",
    )
    rows: list[list[Any]] = Field(
        ...,
        max_length=_MAX_INSIGHT_ROWS,
        description="Data rows; each row is a list aligned with columns.",
    )
    context_hint: str | None = Field(
        default=None,
        max_length=500,
        description="Optional context (e.g. dashboard title or generating question).",
    )


class InsightResponse(BaseModel):
    """Response for POST /ai/insights on success.

    Attributes:
        summary: A 2-4 sentence plain-text summary whose numbers are all
            traceable to the supplied result set (guardrail enforced).
    """

    summary: str = Field(description="Validated insight summary (2-4 sentences).")


class InsightError(BaseModel):
    """Structured error body for POST /ai/insights.

    Attributes:
        detail: Human-readable reason (safe to display to the user).
        code: Machine-readable error code.
    """

    detail: str
    code: str


# ---------------------------------------------------------------------------
# Insight summaries endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/insights",
    response_model=InsightResponse,
    status_code=200,
    responses={
        422: {
            "model": InsightError,
            "description": (
                "Summary generation failed the no-invented-numbers guardrail. "
                "All numbers in the generated summary must be traceable to the "
                "supplied result set."
            ),
        },
        503: {"description": "LLM provider temporarily unavailable"},
    },
    summary="Generate a validated insight summary from an already-computed result set",
    description=(
        "Accepts an already-computed result set (columns + rows, same shape as QueryResponse) "
        "and generates a 2-4 sentence natural-language summary via the LLM.\n\n"
        "**No-invented-numbers guardrail**: after generation, every numeric token in the "
        "summary is verified against the supplied data. If the summary contains a number "
        "that cannot be traced to any cell value (allowing for thousands separators, "
        "currency symbols, percentages, and sensible rounding), the endpoint fails closed "
        "with a 422 error. One bounded regeneration is attempted before failing.\n\n"
        "The tenant scope is resolved from the authenticated JWT — the caller cannot "
        "influence the tenant context via the request body."
    ),
)
async def generate_insight(
    payload: InsightRequest,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    svc: InsightService = Depends(get_insight_service),  # noqa: B008
) -> InsightResponse:
    """Generate a validated 2-4 sentence insight summary from a result set.

    Fail-closed contract:
    - Guardrail failure (invented number) → 422 with a safe message.
    - LLM provider error → 503 with a safe message; key never leaked.
    """
    try:
        summary = await svc.summarise(
            ctx,
            columns=payload.columns,
            rows=payload.rows,
            context_hint=payload.context_hint,
        )
    except InsightGuardrailError as exc:
        logger.info(
            "Insight guardrail rejected: tenant_id=%r reason=%r",
            ctx.tenant_id,
            exc.reason,
        )
        raise HTTPException(
            status_code=422,
            detail=exc.reason,
        ) from exc
    except LLMProviderError as exc:
        logger.error(
            "Insight LLM provider error: tenant_id=%r provider=%r status=%r",
            ctx.tenant_id,
            exc.provider,
            exc.status_code,
        )
        raise HTTPException(
            status_code=503,
            detail="AI provider is temporarily unavailable. Please try again.",
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:  # fail closed; never leak internals
        # Any other failure (template load, unexpected error) is surfaced as a
        # generic 503 — the internal message (which may contain infra detail) is
        # logged, never returned to the client.
        logger.exception("Insight generation failed: tenant_id=%r", ctx.tenant_id)
        raise HTTPException(
            status_code=503,
            detail="AI provider is temporarily unavailable. Please try again.",
        ) from exc

    return InsightResponse(summary=summary)


# ---------------------------------------------------------------------------
# Dataset suggestions (Task 4.5b): request / response schemas
# ---------------------------------------------------------------------------


class SuggestionItem(BaseModel):
    """One validated chart suggestion.

    Attributes:
        title: Short human-readable title for the suggested chart.
        rationale: One sentence explaining why this chart is useful.
        spec: A fully validated ``ChartSpec`` using the inline dataset path
            (``query.dataset_id`` + ``query.query``).  Column references are
            guaranteed to exist in the dataset's profiled schema.
    """

    title: str = Field(description="Short human-readable chart title.")
    rationale: str = Field(description="One-sentence rationale for the suggestion.")
    spec: ChartSpec = Field(description="Validated ChartSpec (inline dataset path).")


class SuggestionsResponse(BaseModel):
    """Response for POST /ai/datasets/{dataset_id}/suggestions.

    Attributes:
        suggestions: The validated chart suggestions.  May be an empty list if
            the dataset profile did not yield any valid suggestions (not an error).
        note: Optional note when no suggestions survived validation.
    """

    suggestions: list[SuggestionItem] = Field(
        description="Validated chart suggestions (may be empty)."
    )
    note: str | None = Field(
        default=None,
        description="Optional note when no suggestions were generated.",
    )


# ---------------------------------------------------------------------------
# Dataset suggestions endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/datasets/{dataset_id}/suggestions",
    response_model=SuggestionsResponse,
    status_code=200,
    responses={
        404: {"description": "Dataset not found or not owned by the authenticated tenant"},
        503: {"description": "LLM provider or ClickHouse temporarily unavailable"},
    },
    summary="Generate chart suggestions for a connected dataset",
    description=(
        "Profiles a tenant-owned dataset (column names/types, cardinality, numeric "
        "stats, PII-capped sample values) and generates 3-5 validated ChartSpec "
        "suggestions grounded on the profile.\n\n"
        "**Ownership enforcement**: the dataset is resolved via "
        "``DatasetService.get_for_tenant`` before any profiling occurs.  A dataset "
        "not owned by the authenticated tenant returns 404 (indistinguishable from "
        "not-found, to prevent cross-tenant existence leaks).\n\n"
        "**Column allow-list**: every column referenced in a suggested ChartSpec must "
        "exist in the profiled schema.  Suggestions referencing invented columns are "
        "silently dropped.  If none survive, an empty suggestions list is returned "
        "with a note — the endpoint never 500s.\n\n"
        "The tenant scope and dataset ownership are resolved entirely from the "
        "authenticated JWT + server-side DB — never from the request body."
    ),
)
async def dataset_suggestions(
    dataset_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    svc: SuggestionsService = Depends(get_suggestions_service),  # noqa: B008
) -> SuggestionsResponse:
    """Generate validated chart suggestions for a tenant-owned dataset.

    Fail-closed contract:
    - Dataset not found / not owned by tenant → 404 (raised by DatasetService).
    - LLM provider error → 503 with a safe message; key never leaked.
    - Invalid suggestions → dropped silently; empty list returned with note.
    """
    try:
        validated_suggestions = await svc.suggest(ctx, dataset_id=dataset_id)
    except LLMProviderError as exc:
        logger.error(
            "Suggestions LLM provider error: tenant_id=%r dataset_id=%r "
            "provider=%r status=%r",
            ctx.tenant_id,
            dataset_id,
            exc.provider,
            exc.status_code,
        )
        raise HTTPException(
            status_code=503,
            detail="AI provider is temporarily unavailable. Please try again.",
        ) from exc
    except HTTPException:
        # e.g. the 404 raised by DatasetService when the dataset is not owned by
        # this tenant — preserve it (do not mask as 503).
        raise
    except Exception as exc:  # fail closed; never leak internals
        # Profiling can hit ClickHouse / infra errors whose messages may contain
        # schema names or query fragments. Log them, return a generic 503.
        logger.exception(
            "Suggestions failed: tenant_id=%r dataset_id=%r", ctx.tenant_id, dataset_id
        )
        raise HTTPException(
            status_code=503,
            detail="AI provider is temporarily unavailable. Please try again.",
        ) from exc

    items = [
        SuggestionItem(title=s.title, rationale=s.rationale, spec=s.spec)
        for s in validated_suggestions
    ]

    note: str | None = None
    if not items:
        note = (
            "No chart suggestions could be generated for this dataset. "
            "The dataset may not have sufficient structure for automatic suggestions."
        )
        logger.info(
            "Suggestions: tenant_id=%r dataset_id=%r — no valid suggestions returned",
            ctx.tenant_id,
            dataset_id,
        )

    return SuggestionsResponse(suggestions=items, note=note)


# ---------------------------------------------------------------------------
# Chat over the semantic layer (#11): grounded tool-calling
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    """Request body for POST /ai/chat."""

    message: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="A natural-language question about the tenant's data.",
    )


class ChatResponse(BaseModel):
    """Response for POST /ai/chat.

    Attributes:
        answer: The assistant's grounded answer (figures trace to tool results).
        tools_used: The grounded tools the assistant called (for transparency).
        chart: A validated ChartSpec when the assistant generated a chart (via the
            nl_to_chart tool), for the client to render and pin to a dashboard (#12).
    """

    answer: str = Field(description="Grounded natural-language answer.")
    tools_used: list[str] = Field(description="Names of the tools the assistant called.")
    chart: ChartSpec | None = Field(
        default=None,
        description="Validated chart spec when the assistant generated one; else null.",
    )


@router.post(
    "/chat",
    response_model=ChatResponse,
    status_code=200,
    responses={503: {"description": "LLM provider or semantic layer unavailable"}},
    summary="Chat over the governed semantic layer via grounded tool-calling",
    description=(
        "Answers a natural-language question by running an LLM tool-dispatch loop. "
        "The model may call only grounded, tenant-scoped tools (list/query semantic "
        "models, validated NL→SQL) — there is no raw-table or arbitrary-SQL path "
        "(golden rule #3). The tenant scope is resolved from the JWT; the model "
        "cannot widen it. Tool failures are handled gracefully; provider/semantic "
        "outages return 503 with a safe message."
    ),
)
async def chat(
    payload: ChatRequest,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    svc: ChatService = Depends(get_chat_service),  # noqa: B008
) -> ChatResponse:
    """Answer a question over the tenant's governed semantic layer."""
    try:
        result = await svc.ask(ctx, payload.message)
    except LLMProviderError as exc:
        logger.error(
            "Chat LLM provider error: tenant_id=%r provider=%r status=%r",
            ctx.tenant_id,
            exc.provider,
            exc.status_code,
        )
        raise HTTPException(
            status_code=503,
            detail="AI provider is temporarily unavailable. Please try again.",
        ) from exc
    return ChatResponse(
        answer=result.answer, tools_used=result.tools_used, chart=result.chart
    )
