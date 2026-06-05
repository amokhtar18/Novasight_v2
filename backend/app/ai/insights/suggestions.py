"""Source-based suggestions service — sub-feature (b).

Profiles a tenant-owned dataset and generates 3-5 validated ChartSpec
suggestions grounded on the profile columns, following the four-stage
nl-to-sql-grounding pattern:

Stage 1  Ground   -- resolve the dataset via ``DatasetService.get_for_tenant``
                    (tenant ownership enforced; 404 if not theirs); then build
                    the DatasetProfile using ``DatasetProfiler`` (column types,
                    cardinality, stats, PII-capped sample values).
Stage 2  Generate -- call the LLM through the gateway with the
                    ``suggestions/v1`` prompt template, injecting the profile.
Stage 3  Validate -- each suggestion is validated:
                    (1) schema-strict against ChartSpec;
                    (2) column allow-list: every referenced column must exist
                        in the profiled column set.
                    Invalid suggestions are dropped; none surviving → empty
                    list with a note (no 500).
Stage 4  Return   -- return ``{ suggestions: [...] }`` (title + rationale +
                    validated ChartSpec per entry).

## Hard rules

- Dataset ownership is ALWAYS verified via ``DatasetService.get_for_tenant``.
  A dataset not owned by the tenant 404s and is NEVER profiled.
- The tenant db comes from ``ctx.clickhouse_db`` (server-resolved) — never
  from the request body.
- All profiling queries run through ``ClickHouseDatasetService.run_read_only_query``
  (read-only, bound to the tenant's ClickHouse DB).
- The LLM must not invent columns; the allow-list enforced in the validator
  is the profiled column names.
- Raw provider errors and API keys are never leaked.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import Depends

from app.ai.gateway import (
    LLMGateway,
    LLMRequest,
    PromptLoader,
    get_llm_gateway,
    get_prompt_loader,
)
from app.ai.insights.profiler import DatasetProfile, DatasetProfiler
from app.ai.insights.suggestion_validator import ValidatedSuggestion, validate_suggestions
from app.services.clickhouse_datasets import (
    ClickHouseDatasetService,
    get_clickhouse_dataset_service,
)
from app.services.datasets import DatasetService, get_dataset_service
from app.tenancy.context import TenantContext

logger = logging.getLogger(__name__)

# Prompt template coordinates
_TEMPLATE_NAME = "suggestions"
_TEMPLATE_VERSION = "v1"


class SuggestionsService:
    """Generate validated chart suggestions for a tenant-owned dataset.

    All external dependencies are injected via the constructor so the class is
    trivially testable without live infra.

    Args:
        gateway: LLM gateway facade.
        prompt_loader: Versioned prompt template loader.
        dataset_service: Service for resolving tenant-owned datasets.
        ch_svc: Tenant-scoped ClickHouse dataset service (profiling queries).
    """

    def __init__(
        self,
        gateway: LLMGateway,
        prompt_loader: PromptLoader,
        dataset_service: DatasetService,
        ch_svc: ClickHouseDatasetService,
    ) -> None:
        self._gateway = gateway
        self._loader = prompt_loader
        self._dataset_svc = dataset_service
        self._ch_svc = ch_svc

    # ------------------------------------------------------------------
    # Public pipeline entry point
    # ------------------------------------------------------------------

    async def suggest(
        self,
        ctx: TenantContext,
        *,
        dataset_id: uuid.UUID,
    ) -> list[ValidatedSuggestion]:
        """Generate and return validated chart suggestions for a tenant dataset.

        Ownership is verified by ``DatasetService.get_for_tenant`` (raises
        404 HTTPException if the dataset is not owned by this tenant — the
        caller handles it at the router level).

        Args:
            ctx: Server-resolved tenant context.
            dataset_id: UUID of the dataset to suggest charts for.

        Returns:
            A list of ``ValidatedSuggestion`` objects (may be empty if the
            LLM produces no valid suggestions).

        Raises:
            HTTPException(404): If the dataset is not owned by this tenant.
        """
        # ------------------------------------------------------------------
        # Stage 1 -- Ground: resolve dataset + profile it
        # ------------------------------------------------------------------
        dataset = await self._dataset_svc.get_for_tenant(ctx, dataset_id)

        profiler = DatasetProfiler(self._ch_svc)
        profile = profiler.profile(ctx, dataset)

        allowed_columns = {col.name for col in profile.columns}

        logger.info(
            "SuggestionsService.suggest: tenant_id=%r dataset_id=%r "
            "columns=%d rows=%d",
            ctx.tenant_id,
            str(dataset_id),
            len(profile.columns),
            profile.total_rows,
        )

        # ------------------------------------------------------------------
        # Stage 2 -- Generate
        # ------------------------------------------------------------------
        raw_output = await self._generate(ctx, profile=profile)

        # ------------------------------------------------------------------
        # Stage 3 -- Validate
        # ------------------------------------------------------------------
        raw_suggestions = self._parse_llm_output(ctx, raw_output)
        suggestions = validate_suggestions(
            raw_suggestions,
            allowed_columns=allowed_columns,
            dataset_id_str=str(dataset_id),
        )

        logger.info(
            "SuggestionsService.suggest done: tenant_id=%r dataset_id=%r "
            "suggestions_valid=%d",
            ctx.tenant_id,
            str(dataset_id),
            len(suggestions),
        )

        # ------------------------------------------------------------------
        # Stage 4 -- Return
        # ------------------------------------------------------------------
        return suggestions

    # ------------------------------------------------------------------
    # Stage implementations
    # ------------------------------------------------------------------

    async def _generate(self, ctx: TenantContext, *, profile: DatasetProfile) -> str:
        """Call the LLM with the dataset profile injected (stage 2)."""
        profile_text = profile.to_prompt_text()
        dataset_id_str = profile.dataset_id

        system_prompt = self._loader.render(
            _TEMPLATE_NAME,
            _TEMPLATE_VERSION,
            "system",
            dataset_profile=profile_text,
            dataset_id=dataset_id_str,
        )
        user_prompt = self._loader.render(
            _TEMPLATE_NAME,
            _TEMPLATE_VERSION,
            "user",
        )

        logger.info(
            "SuggestionsService._generate: tenant_id=%r dataset_id=%r",
            ctx.tenant_id,
            dataset_id_str,
        )

        response = await self._gateway.complete(
            LLMRequest(system=system_prompt, user_message=user_prompt),
            ctx=ctx,
        )

        raw = response.text.strip()

        logger.info(
            "SuggestionsService._generate: tenant_id=%r output_tokens=%d preview=%r",
            ctx.tenant_id,
            response.usage.get("output_tokens", 0),
            raw[:120],
        )

        return raw

    def _parse_llm_output(self, ctx: TenantContext, raw_output: str) -> list[Any]:
        """Parse the LLM output as a JSON array of suggestion objects.

        On any parse failure, logs a warning and returns an empty list
        (fail-safe — the caller will return an empty suggestions list).
        """
        try:
            parsed = json.loads(raw_output)
        except json.JSONDecodeError as exc:
            logger.warning(
                "SuggestionsService: tenant_id=%r JSON parse error: %s",
                ctx.tenant_id,
                exc,
            )
            return []

        if not isinstance(parsed, list):
            logger.warning(
                "SuggestionsService: tenant_id=%r LLM returned non-list JSON type=%r",
                ctx.tenant_id,
                type(parsed).__name__,
            )
            return []

        return parsed


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


def get_suggestions_service(
    gateway: LLMGateway = Depends(get_llm_gateway),  # noqa: B008
    prompt_loader: PromptLoader = Depends(get_prompt_loader),  # noqa: B008
    dataset_service: DatasetService = Depends(get_dataset_service),  # noqa: B008
    ch_svc: ClickHouseDatasetService = Depends(get_clickhouse_dataset_service),  # noqa: B008
) -> SuggestionsService:
    """FastAPI dependency: assemble a ``SuggestionsService`` from request-scope deps."""
    return SuggestionsService(
        gateway=gateway,
        prompt_loader=prompt_loader,
        dataset_service=dataset_service,
        ch_svc=ch_svc,
    )
