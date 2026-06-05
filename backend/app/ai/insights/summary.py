"""Insight summary service — sub-feature (a).

Produces a 2-4 sentence natural-language summary of an already-computed
QueryResponse result set, following the four-stage nl-to-sql-grounding pattern:

Stage 1  Ground   -- the result set IS the grounding context; serialise it to
                    a compact, PII-aware text representation for the prompt.
Stage 2  Generate -- call the LLM through the gateway with the
                    ``insights/v1`` prompt template, injecting the result set.
Stage 3  Validate -- apply the no-invented-numbers guardrail:
                    every numeric token in the summary must be traceable to
                    a cell value in the result set.  One bounded regeneration
                    is attempted before failing closed.
Stage 4  Return   -- return the validated summary text.

## Hard rules (from nl-to-sql-grounding skill)

- Summaries are produced from the already-computed result set, never from
  free-form generation.
- No numbers invented by the LLM are permitted (guardrail enforced here).
- No tenant data crosses into another tenant's prompt or cache.
- Raw provider errors and API keys are never leaked to the caller.
- Prompts and outputs are logged with tenant context; no PII or secrets.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import Depends

from app.ai.gateway import (
    LLMGateway,
    LLMRequest,
    PromptLoader,
    get_llm_gateway,
    get_prompt_loader,
)
from app.ai.insights.guardrail import InsightGuardrailError, verify_no_invented_numbers
from app.tenancy.context import TenantContext

logger = logging.getLogger(__name__)

# Prompt template coordinates (loaded from settings.ai.prompt_template_dir)
_TEMPLATE_NAME = "insights"
_TEMPLATE_VERSION = "v1"

# Safety caps for the result set injected into the prompt.
# We never dump thousands of rows into the prompt — it would be slow, expensive,
# and may contain PII.  Cap at a sensible preview.
_MAX_PROMPT_ROWS = 100
_MAX_PROMPT_COLS = 20

# Maximum number of regeneration attempts (1 initial + 1 retry = 2 total).
_MAX_ATTEMPTS = 2


def _serialise_result_set(
    columns: list[str],
    rows: list[list[Any]],
) -> str:
    """Serialise the result set to a compact string for prompt injection.

    - Caps the number of rows at ``_MAX_PROMPT_ROWS`` and columns at
      ``_MAX_PROMPT_COLS`` to keep the prompt bounded.
    - Uses a simple CSV-like format: first line is headers, then data rows.
      Avoids JSON to keep the prompt text compact and readable.
    - Appends a note if the result was truncated so the LLM is aware.
    """
    safe_cols = columns[:_MAX_PROMPT_COLS]
    safe_rows = rows[:_MAX_PROMPT_ROWS]

    col_indices = list(range(len(safe_cols)))
    lines: list[str] = [", ".join(safe_cols)]
    for row in safe_rows:
        cells = [str(row[i]) if i < len(row) else "" for i in col_indices]
        lines.append(", ".join(cells))

    text = "\n".join(lines)

    truncation_notes: list[str] = []
    if len(rows) > _MAX_PROMPT_ROWS:
        truncation_notes.append(
            f"[Note: showing first {_MAX_PROMPT_ROWS} of {len(rows)} rows]"
        )
    if len(columns) > _MAX_PROMPT_COLS:
        truncation_notes.append(
            f"[Note: showing first {_MAX_PROMPT_COLS} of {len(columns)} columns]"
        )
    if truncation_notes:
        text += "\n" + " ".join(truncation_notes)

    return text


class InsightService:
    """Generate a validated insight summary for an already-computed result set.

    All external dependencies are injected via the constructor so the class is
    trivially testable without live infra.

    Args:
        gateway: LLM gateway facade.
        prompt_loader: Versioned prompt template loader.
    """

    def __init__(
        self,
        gateway: LLMGateway,
        prompt_loader: PromptLoader,
    ) -> None:
        self._gateway = gateway
        self._loader = prompt_loader

    # ------------------------------------------------------------------
    # Public pipeline entry point
    # ------------------------------------------------------------------

    async def summarise(
        self,
        ctx: TenantContext,
        *,
        columns: list[str],
        rows: list[list[Any]],
        context_hint: str | None = None,
    ) -> str:
        """Generate a validated 2-4 sentence insight summary from a result set.

        The result set is the caller's already-computed dashboard data.  The
        LLM is given the result set as context and is instructed not to invent
        numbers.  After generation the no-invented-numbers guardrail verifies
        the output; if it fails one bounded regeneration is attempted.

        Args:
            ctx: Server-resolved tenant context.  Used for logging only — the
                result set IS the data, so there is no additional data fetch.
            columns: Column names from the QueryResponse.
            rows: Data rows from the QueryResponse.
            context_hint: Optional hint (e.g. the dashboard title or the
                original question that produced the result set) that can be
                prepended to the user prompt for context.

        Returns:
            A validated plain-text summary (2-4 sentences).

        Raises:
            InsightGuardrailError: If two consecutive generations both contain
                invented numbers (fail closed).
        """
        if not rows:
            logger.info(
                "InsightService.summarise: tenant_id=%r — result set is empty, "
                "returning canned message",
                ctx.tenant_id,
            )
            return "No data is available for this result set."

        result_set_text = _serialise_result_set(columns, rows)

        # The guardrail must verify against EXACTLY what the LLM saw — the capped
        # preview, not the full payload. This (a) bounds the guardrail's work to
        # _MAX_PROMPT_ROWS by _MAX_PROMPT_COLS regardless of input size (a number
        # outside the preview can't appear in the output anyway), and (b) avoids a
        # false negative where a hallucinated number traces to an unseen cell.
        safe_cols = columns[:_MAX_PROMPT_COLS]
        safe_rows = [row[: len(safe_cols)] for row in rows[:_MAX_PROMPT_ROWS]]

        logger.info(
            "InsightService.summarise: tenant_id=%r rows=%d cols=%d",
            ctx.tenant_id,
            len(rows),
            len(columns),
        )

        last_error: InsightGuardrailError | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            summary = await self._generate(
                ctx, result_set_text=result_set_text, context_hint=context_hint
            )
            try:
                verify_no_invented_numbers(summary, columns=safe_cols, rows=safe_rows)
                logger.info(
                    "InsightService.summarise: tenant_id=%r attempt=%d guardrail=PASS",
                    ctx.tenant_id,
                    attempt,
                )
                return summary
            except InsightGuardrailError as exc:
                last_error = exc
                logger.warning(
                    "InsightService.summarise: tenant_id=%r attempt=%d guardrail=FAIL "
                    "reason=%r",
                    ctx.tenant_id,
                    attempt,
                    exc.reason,
                )

        # Both attempts failed — fail closed.
        assert last_error is not None
        raise last_error

    # ------------------------------------------------------------------
    # Stage implementations
    # ------------------------------------------------------------------

    async def _generate(
        self, ctx: TenantContext, *, result_set_text: str, context_hint: str | None = None
    ) -> str:
        """Call the LLM with the result set injected into the prompt (stages 2 & 3)."""
        system_prompt = self._loader.render(
            _TEMPLATE_NAME,
            _TEMPLATE_VERSION,
            "system",
            result_set=result_set_text,
        )

        # The hint (e.g. the dashboard title or originating question) orients the
        # summary. It is descriptive context only — the no-invented-numbers
        # guardrail still runs on the output regardless of what the hint says.
        user_message = "Summarise the result set."
        if context_hint:
            user_message = f"Context: {context_hint}\n\n{user_message}"

        response = await self._gateway.complete(
            LLMRequest(system=system_prompt, user_message=user_message),
            ctx=ctx,
        )

        summary = response.text.strip()

        logger.info(
            "InsightService._generate: tenant_id=%r output_tokens=%d preview=%r",
            ctx.tenant_id,
            response.usage.get("output_tokens", 0),
            summary[:100],  # short preview only — never log full output
        )

        return summary


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


def get_insight_service(
    gateway: LLMGateway = Depends(get_llm_gateway),  # noqa: B008
    prompt_loader: PromptLoader = Depends(get_prompt_loader),  # noqa: B008
) -> InsightService:
    """FastAPI dependency: assemble an ``InsightService`` from request-scope deps."""
    return InsightService(gateway=gateway, prompt_loader=prompt_loader)
