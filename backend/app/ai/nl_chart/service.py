"""NL→Chart service — orchestrates the four-stage grounded, validated pipeline.

Stage 1  Ground   -- pull governed cubes/measures/dimensions from Cube ``/meta``
                    for the current tenant only; build the allow-list of metric
                    and dimension identifiers.
Stage 2  Generate -- call the LLM through the gateway with the
                    ``nl_to_chart/v1`` prompt template, injecting the grounding
                    context.
Stage 3  Validate -- parse the LLM output as JSON and validate it STRICTLY
                    against ``ChartSpec`` (extra fields forbidden, invariants
                    enforced, AI-path gate, grounding allow-list).
Stage 4  Resolve  -- execute the chart query via ``SemanticLayerClient.query``
                    (tenant-scoped) and return a typed
                    ``{spec: ChartSpec, data: QueryResponse}`` pair.

## Hard rules (from nl-to-sql-grounding skill)

- The LLM never receives raw physical table names — only governed semantic-layer
  objects from the Cube meta response.
- No tenant's data, context, or cache entry crosses into another tenant.
- On ANY generation or validation failure: FAIL CLOSED.  Return a safe error to
  the caller; never resolve data from an unvalidated spec; never leak raw provider
  errors or the API key.
- Prompts and responses are logged with tenant context; no PII or secrets.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from fastapi import Depends

from app.ai.gateway import (
    LLMGateway,
    LLMRequest,
    PromptLoader,
    get_llm_gateway,
    get_prompt_loader,
)
from app.ai.nl_chart.grounding import ChartGroundingContext, build_chart_grounding_context
from app.ai.nl_chart.validator import validate_chart_spec
from app.ai.semantic.client import SemanticLayerClient, get_semantic_layer_client
from app.schemas.chart import ChartSpec
from app.schemas.query import QueryResponse
from app.tenancy.context import TenantContext

logger = logging.getLogger(__name__)

# Prompt template coordinates.
_TEMPLATE_NAME = "nl_to_chart"
_TEMPLATE_VERSION = "v1"


class NLToChartService:
    """Orchestrate the Ground→Generate→Validate→Resolve pipeline for chart generation.

    All external dependencies are injected via the constructor so the class is
    trivially testable without live infra.

    Args:
        gateway: LLM gateway facade.
        prompt_loader: Versioned prompt template loader.
        semantic_client: Tenant-scoped Cube semantic layer client.
    """

    def __init__(
        self,
        gateway: LLMGateway,
        prompt_loader: PromptLoader,
        semantic_client: SemanticLayerClient,
    ) -> None:
        self._gateway = gateway
        self._loader = prompt_loader
        self._semantic = semantic_client

    # ------------------------------------------------------------------
    # Public pipeline entry point
    # ------------------------------------------------------------------

    async def generate(
        self,
        ctx: TenantContext,
        *,
        request: str,
    ) -> tuple[ChartSpec, QueryResponse]:
        """Translate ``request`` into a validated ChartSpec and resolve its data.

        Args:
            ctx: Server-resolved tenant context (from ``get_tenant_context``).
                All semantic-layer queries are scoped to this tenant only.
            request: The natural-language chart request from the user.

        Returns:
            A ``(ChartSpec, QueryResponse)`` pair.  The ``ChartSpec`` is fully
            validated; the ``QueryResponse`` has columns aligned to
            ``encoding.x`` + ``encoding.series[].field`` so the frontend
            renderer can consume them directly.

        Raises:
            ChartValidationError: If generation or validation fails.
            CubeAuthError: If the semantic layer rejects the tenant JWT.
            CubeQueryError: If the semantic layer returns an unexpected error.
        """
        # ------------------------------------------------------------------
        # Stage 1 -- Ground
        # ------------------------------------------------------------------
        grounding = await self._ground(ctx)

        # ------------------------------------------------------------------
        # Stage 2 -- Generate
        # ------------------------------------------------------------------
        raw_output = await self._generate(ctx, request=request, grounding=grounding)

        # ------------------------------------------------------------------
        # Stage 3 -- Validate (BEFORE any data resolution)
        # ------------------------------------------------------------------
        spec = self._validate(raw_output, grounding=grounding)

        # ------------------------------------------------------------------
        # Stage 4 -- Resolve data
        # ------------------------------------------------------------------
        data = await self._resolve(ctx, spec=spec)

        return spec, data

    # ------------------------------------------------------------------
    # Stage implementations
    # ------------------------------------------------------------------

    async def _ground(self, ctx: TenantContext) -> ChartGroundingContext:
        """Pull governed semantic-layer schema for this tenant (stage 1)."""
        meta = await self._semantic.meta(ctx)
        grounding = build_chart_grounding_context(meta)

        cubes_list = meta.get("cubes") or []
        logger.info(
            "NL->Chart ground: tenant_id=%r cubes=%d metrics=%r dimensions=%r",
            ctx.tenant_id,
            len(cubes_list),
            sorted(grounding.allowed_metrics),
            sorted(grounding.allowed_dimensions),
        )
        return grounding

    async def _generate(
        self,
        ctx: TenantContext,
        *,
        request: str,
        grounding: ChartGroundingContext,
    ) -> str:
        """Call the LLM with the grounding context injected (stage 2)."""
        system_prompt = self._loader.render(
            _TEMPLATE_NAME,
            _TEMPLATE_VERSION,
            "system",
            tenant_id=ctx.tenant_id,
            semantic_context=grounding.semantic_text,
        )
        user_prompt = self._loader.render(
            _TEMPLATE_NAME,
            _TEMPLATE_VERSION,
            "user",
            request=request,
        )

        logger.info(
            "NL->Chart generate: tenant_id=%r request_len=%d",
            ctx.tenant_id,
            len(request),
        )

        response = await self._gateway.complete(
            LLMRequest(system=system_prompt, user_message=user_prompt),
            ctx=ctx,
        )

        raw_output = response.text.strip()

        logger.info(
            "NL->Chart generate: tenant_id=%r output_tokens=%d preview=%r",
            ctx.tenant_id,
            response.usage.get("output_tokens", 0),
            raw_output[:120],  # preview only — never log full output
        )

        return raw_output

    def _validate(self, raw_output: str, *, grounding: ChartGroundingContext) -> ChartSpec:
        """Validate the LLM output against ChartSpec and the grounding allow-list (stage 3).

        Called BEFORE any data resolution.  On any guardrail violation a
        ``ChartValidationError`` is raised; the caller must NEVER resolve data
        from an unvalidated spec.
        """
        return validate_chart_spec(
            raw_output,
            allowed_metrics=grounding.allowed_metrics,
            allowed_dimensions=grounding.allowed_dimensions,
        )

    async def _resolve(self, ctx: TenantContext, *, spec: ChartSpec) -> QueryResponse:
        """Execute the chart metric query via the semantic layer (stage 4).

        Calls ``SemanticLayerClient.query`` with:
        - ``measures`` = ``spec.query.metric_refs`` (governed measure names)
        - ``dimensions`` = ``[spec.encoding.x]`` if ``encoding.x`` is set,
          else ``[]`` for table charts.

        Transforms the returned ``CubeRow`` list into a ``QueryResponse``
        whose ``columns`` are ``[encoding.x] + [s.field for s in encoding.series]``
        (aligned exactly with the fields the frontend renderer uses).

        Args:
            ctx: The server-resolved tenant context.
            spec: A fully validated ``ChartSpec``.

        Returns:
            A ``QueryResponse`` with columns and rows aligned to the spec encoding.
        """
        measures: list[str] = list(spec.query.metric_refs)
        dimensions: list[str] = [spec.encoding.x] if spec.encoding.x else []

        logger.info(
            "NL->Chart resolve: tenant_id=%r measures=%r dimensions=%r",
            ctx.tenant_id,
            measures,
            dimensions,
        )

        cube_rows = await self._semantic.query(
            ctx,
            measures=measures,
            dimensions=dimensions,
        )

        # Build the column list: dimension first, then each series field (in order).
        # series[].field mirrors the metric_refs but is the display reference column name.
        columns: list[str] = []
        if spec.encoding.x:
            columns.append(spec.encoding.x)
        for series in spec.encoding.series:
            columns.append(series.field)

        # Build rows aligned to ``columns``.  Each CubeRow is a dict keyed by
        # fully-qualified name (e.g. ``"regional_sales.region"``).
        # Defense in depth: the validator guarantees every column (x + series
        # fields) is queried, so a missing key should not happen — but if Cube ever
        # omits a requested column, warn rather than silently emit null data.
        missing_cols = {
            col for cube_row in cube_rows for col in columns if col not in cube_row
        }
        if missing_cols:
            logger.warning(
                "NL->Chart resolve: Cube response missing requested column(s) %r "
                "for tenant_id=%r — emitting null for those cells",
                sorted(missing_cols),
                ctx.tenant_id,
            )
        rows: list[list[Any]] = []
        for cube_row in cube_rows:
            row: list[Any] = []
            for col in columns:
                value = cube_row.get(col)
                # Cast Decimal to float so JSON serialisation is safe.
                if isinstance(value, Decimal):
                    row.append(float(value))
                elif value is None:
                    row.append(None)
                else:
                    row.append(value)
            rows.append(row)

        data = QueryResponse(
            columns=columns,
            rows=rows,
            row_count=len(rows),
        )

        logger.info(
            "NL->Chart resolve done: tenant_id=%r columns=%r row_count=%d",
            ctx.tenant_id,
            columns,
            data.row_count,
        )

        return data


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


def get_nl_to_chart_service(
    gateway: LLMGateway = Depends(get_llm_gateway),  # noqa: B008
    prompt_loader: PromptLoader = Depends(get_prompt_loader),  # noqa: B008
    semantic_client: SemanticLayerClient = Depends(get_semantic_layer_client),  # noqa: B008
) -> NLToChartService:
    """FastAPI dependency: assemble an ``NLToChartService`` from request-scope deps."""
    return NLToChartService(
        gateway=gateway,
        prompt_loader=prompt_loader,
        semantic_client=semantic_client,
    )
