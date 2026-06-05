"""NL->SQL service -- orchestrates the four-stage grounded, validated pipeline.

Stage 1  Ground   -- pull governed cubes/measures/dimensions from Cube ``/meta``
                    for the current tenant only.
Stage 2  Generate -- call the LLM through the gateway with the ``nl_to_sql v1``
                    prompt template, injecting the grounding context.
Stage 3  Validate -- parse the generated SQL with sqlglot; reject unless it is a
                    single read-only SELECT that references only allow-listed
                    objects and is qualified with the correct tenant DB.
Stage 4  Execute  -- run the validated SQL via ``run_read_only_query`` (read-only
                    enforced at the ClickHouse connection level too).

## Hard rules (from nl-to-sql-grounding skill)

- The LLM never receives raw physical table names -- only governed semantic-layer
  objects from the Cube meta response.
- No write/DDL ever reaches ClickHouse from generated SQL.
- No tenant's data, context, or cache entry crosses into another tenant.
- On ANY generation or validation failure: FAIL CLOSED.  Return a safe error to
  the caller; never execute unvalidated output; never leak raw provider errors
  or the API key.
- Prompts and responses are logged with tenant context; no PII or secrets.
"""
from __future__ import annotations

import logging

from fastapi import Depends

from app.ai.gateway import (
    LLMGateway,
    LLMRequest,
    PromptLoader,
    get_llm_gateway,
    get_prompt_loader,
)
from app.ai.nl_sql.grounding import GroundingContext, build_grounding_context
from app.ai.nl_sql.validator import validate_and_cap
from app.ai.semantic.client import (
    SemanticLayerClient,
    get_semantic_layer_client,
)
from app.core.clickhouse import QueryResult
from app.core.config import Settings, get_settings
from app.services.clickhouse_datasets import (
    ClickHouseDatasetService,
    get_clickhouse_dataset_service,
)
from app.tenancy.context import TenantContext

logger = logging.getLogger(__name__)

# Prompt template coordinates.
_TEMPLATE_NAME = "nl_to_sql"
_TEMPLATE_VERSION = "v1"


class NLToSQLService:
    """Orchestrate the Ground->Generate->Validate->Execute pipeline.

    All four dependencies are injected via the constructor so the class is
    trivially testable without live infra.

    Args:
        gateway: LLM gateway facade.
        prompt_loader: Versioned prompt template loader.
        semantic_client: Tenant-scoped Cube semantic layer client.
        ch_dataset_svc: ClickHouse read-only query runner.
        settings: Application settings (for ``max_query_rows`` and the
            governed table allow-list).
    """

    def __init__(
        self,
        gateway: LLMGateway,
        prompt_loader: PromptLoader,
        semantic_client: SemanticLayerClient,
        ch_dataset_svc: ClickHouseDatasetService,
        settings: Settings,
    ) -> None:
        self._gateway = gateway
        self._loader = prompt_loader
        self._semantic = semantic_client
        self._ch = ch_dataset_svc
        self._settings = settings

    # ------------------------------------------------------------------
    # Public pipeline entry point
    # ------------------------------------------------------------------

    async def query(
        self,
        ctx: TenantContext,
        *,
        question: str,
    ) -> tuple[str, QueryResult]:
        """Translate ``question`` to SQL and execute it.

        Returns:
            A ``(validated_sql, QueryResult)`` pair.  The validated SQL is
            returned alongside the result so callers can surface it to the
            frontend for transparency.

        Raises:
            SQLValidationError: If generation or validation fails.
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
        raw_sql = await self._generate(ctx, question=question, grounding=grounding)

        # ------------------------------------------------------------------
        # Stage 3 -- Validate (BEFORE any execution)
        # ------------------------------------------------------------------
        validated_sql = self._validate(raw_sql, ctx=ctx)

        # ------------------------------------------------------------------
        # Stage 4 -- Execute
        # ------------------------------------------------------------------
        result = self._execute(ctx, validated_sql)

        return validated_sql, result

    # ------------------------------------------------------------------
    # Stage implementations
    # ------------------------------------------------------------------

    async def _ground(self, ctx: TenantContext) -> GroundingContext:
        """Pull governed semantic-layer schema for this tenant (stage 1)."""
        meta = await self._semantic.meta(ctx)

        # The config allow-list ensures the serving table is always permitted
        # even if Cube does not expose it in the sql_table annotation.
        config_tables: set[str] = {
            self._settings.serving_regional_sales_table.lower()
        }

        grounding = build_grounding_context(meta, config_tables=config_tables)

        cubes_list = meta.get("cubes") or []
        logger.info(
            "NL->SQL ground: tenant_id=%r cubes=%d tables=%r",
            ctx.tenant_id,
            len(cubes_list),
            sorted(grounding.physical_tables),
        )
        return grounding

    async def _generate(
        self,
        ctx: TenantContext,
        *,
        question: str,
        grounding: GroundingContext,
    ) -> str:
        """Call the LLM with the grounding context injected (stage 2)."""
        system_prompt = self._loader.render(
            _TEMPLATE_NAME,
            _TEMPLATE_VERSION,
            "system",
            tenant_id=ctx.tenant_id,
            semantic_context=grounding.semantic_text,
            max_rows=str(self._settings.max_query_rows),
        )
        user_prompt = self._loader.render(
            _TEMPLATE_NAME,
            _TEMPLATE_VERSION,
            "user",
            question=question,
        )

        # Log intent without the full prompt text (which may contain semantic
        # metadata); the question length is safe to log.
        logger.info(
            "NL->SQL generate: tenant_id=%r question_len=%d",
            ctx.tenant_id,
            len(question),
        )

        response = await self._gateway.complete(
            LLMRequest(system=system_prompt, user_message=user_prompt),
            ctx=ctx,
        )

        raw_sql = response.text.strip()

        logger.info(
            "NL->SQL generate: tenant_id=%r output_tokens=%d sql_preview=%r",
            ctx.tenant_id,
            response.usage.get("output_tokens", 0),
            raw_sql[:120],  # preview only -- never log full SQL
        )

        return raw_sql

    def _validate(self, raw_sql: str, *, ctx: TenantContext) -> str:
        """Validate and row-cap the generated SQL (stage 3).

        This is called BEFORE any execution.  On any guardrail violation a
        ``SQLValidationError`` is raised; the caller must NEVER execute the
        raw SQL on error.
        """
        allowed: set[str] = {
            self._settings.serving_regional_sales_table.lower()
        }

        return validate_and_cap(
            raw_sql,
            allowed_tables=allowed,
            tenant_db=ctx.clickhouse_db,
            max_rows=self._settings.max_query_rows,
        )

    def _execute(self, ctx: TenantContext, validated_sql: str) -> QueryResult:
        """Execute the validated SQL in a read-only, tenant-scoped connection (stage 4)."""
        logger.info(
            "NL->SQL execute: tenant_id=%r clickhouse_db=%r",
            ctx.tenant_id,
            ctx.clickhouse_db,
        )
        return self._ch.run_read_only_query(ctx, validated_sql)


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


def get_nl_to_sql_service(
    gateway: LLMGateway = Depends(get_llm_gateway),  # noqa: B008
    prompt_loader: PromptLoader = Depends(get_prompt_loader),  # noqa: B008
    semantic_client: SemanticLayerClient = Depends(get_semantic_layer_client),  # noqa: B008
    ch_dataset_svc: ClickHouseDatasetService = Depends(  # noqa: B008
        get_clickhouse_dataset_service
    ),
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> NLToSQLService:
    """FastAPI dependency: assemble an ``NLToSQLService`` from request-scope deps."""
    return NLToSQLService(
        gateway=gateway,
        prompt_loader=prompt_loader,
        semantic_client=semantic_client,
        ch_dataset_svc=ch_dataset_svc,
        settings=settings,
    )
