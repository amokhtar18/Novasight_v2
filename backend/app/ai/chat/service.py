"""Chat service — the grounded tool-dispatch loop (#11/#12).

The model is given a fixed set of **grounded** tools that delegate to existing,
already-validated services. The loop:

1. send the conversation + tool specs to the gateway (``complete_with_tools``);
2. if the model requested tools, execute each one under the tenant context, feed
   the results back, and repeat (bounded by ``max_turns``);
3. otherwise return the assistant's final text.

Safety (golden rule #3): tools only call the governed semantic layer / validated
NL→SQL path — there is no raw-table or arbitrary-SQL path. Tool failures are
returned to the model as ``is_error`` results (fail closed, but let the model
explain) rather than crashing the request. Tenancy (golden rule #2): every tool
runs with the server-resolved ``TenantContext``.

The dispatch loop is unit-tested with a fake gateway; the live LLM tool-calling
and the provider adapters are verified on the running stack.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Depends
from pydantic import BaseModel

from app.ai.gateway import LLMGateway, get_llm_gateway
from app.ai.gateway.provider import (
    ChatTurn,
    ToolCall,
    ToolChatRequest,
    ToolResultMsg,
    ToolSpec,
)
from app.ai.nl_chart import (
    ChartValidationError,
    NLToChartService,
    get_nl_to_chart_service,
)
from app.ai.nl_sql import NLToSQLService, SQLValidationError, get_nl_to_sql_service
from app.ai.semantic.client import CubeAuthError, CubeQueryError
from app.schemas.chart import ChartSpec
from app.schemas.semantic import SemanticQueryRequest
from app.services.semantic import (
    SemanticService,
    SemanticValidationError,
    get_semantic_service,
)
from app.tenancy.context import TenantContext

logger = logging.getLogger(__name__)

# A tool handler: given the tenant ctx + the model's input, return result text.
ToolHandler = Callable[[TenantContext, dict[str, Any]], Awaitable[str]]

# Hard cap on dispatch loop iterations — bounds cost + prevents runaway tool loops.
_MAX_TURNS = 6
# Cap rows returned to the model so a large result can't blow the context window.
_MAX_TOOL_ROWS = 50

LIST_MODELS = "list_semantic_models"
QUERY_MODEL = "query_semantic_model"
NL_TO_SQL = "nl_to_sql"
NL_TO_CHART = "nl_to_chart"

SYSTEM_PROMPT = (
    "You are NovaSight's analytics assistant. Answer questions about the tenant's "
    "data ONLY by calling the provided tools, which query a governed semantic layer. "
    "Never invent numbers, table names, or columns. First call list_semantic_models "
    "to discover the available measures and dimensions, then query_semantic_model "
    "with fully-qualified names, or nl_to_sql for ad-hoc questions. When the user "
    "asks to chart, plot, graph, or visualize something, call nl_to_chart with a "
    "clear description — the chart is attached to your reply for the user to pin to "
    "a dashboard. If the tools cannot answer, say so plainly. Base every figure you "
    "state on a tool result."
)

# The tool specs advertised to the model (stable; the handlers below execute them).
TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name=LIST_MODELS,
        description=(
            "List the governed semantic models the tenant may query, with each "
            "model's measures and dimensions. Call this first to discover names."
        ),
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    ToolSpec(
        name=QUERY_MODEL,
        description=(
            "Run a structured query against the governed semantic layer. Use "
            "fully-qualified measure/dimension names from list_semantic_models "
            "(e.g. 'regional_sales.total_amount'). Returns columns + rows."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "measures": {"type": "array", "items": {"type": "string"}},
                "dimensions": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": "integer"},
            },
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name=NL_TO_SQL,
        description=(
            "Answer an ad-hoc analytical question by generating validated, "
            "read-only SQL over the governed layer and returning the rows. Use "
            "when the question isn't a simple measures/dimensions lookup."
        ),
        input_schema={
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name=NL_TO_CHART,
        description=(
            "Generate a chart from a natural-language description over the governed "
            "semantic layer. Call this when the user asks to chart, plot, graph, or "
            "visualize data (e.g. 'plot total amount by region'). Returns a short "
            "summary of the generated chart; the chart itself is attached to the "
            "reply so the user can pin it to a dashboard."
        ),
        input_schema={
            "type": "object",
            "properties": {"request": {"type": "string"}},
            "required": ["request"],
            "additionalProperties": False,
        },
    ),
]


def build_handlers(
    semantic: SemanticService,
    nl_sql: NLToSQLService,
    nl_chart: NLToChartService,
    chart_sink: list[ChartSpec],
) -> dict[str, ToolHandler]:
    """Wire the grounded tool handlers from the existing services.

    ``chart_sink`` is a per-request list the ``nl_to_chart`` handler appends each
    generated spec to, so ``ChatService.ask`` can attach the chart to its reply.
    """

    async def list_models(ctx: TenantContext, _input: dict[str, Any]) -> str:
        models = await semantic.list_models(ctx)
        return json.dumps(
            [
                {
                    "name": m.name,
                    "measures": [x.name for x in m.measures],
                    "dimensions": [x.name for x in m.dimensions],
                }
                for m in models
            ]
        )

    async def query_model(ctx: TenantContext, inp: dict[str, Any]) -> str:
        req = SemanticQueryRequest(
            measures=list(inp.get("measures", [])),
            dimensions=list(inp.get("dimensions", [])),
            limit=inp.get("limit"),
        )
        resp = await semantic.query(ctx, req)
        return json.dumps(
            {
                "columns": resp.columns,
                "rows": resp.rows[:_MAX_TOOL_ROWS],
                "row_count": resp.row_count,
            }
        )

    async def nl_to_sql(ctx: TenantContext, inp: dict[str, Any]) -> str:
        sql, result = await nl_sql.query(ctx, question=str(inp.get("question", "")))
        return json.dumps(
            {
                "sql": sql,
                "columns": result.column_names,
                "rows": [list(r) for r in result.rows[:_MAX_TOOL_ROWS]],
            }
        )

    async def nl_to_chart(ctx: TenantContext, inp: dict[str, Any]) -> str:
        spec, data = await nl_chart.generate(ctx, request=str(inp.get("request", "")))
        # Capture the validated spec for the reply (the user pins it to a dashboard);
        # only the latest chart of a turn is surfaced.
        chart_sink.append(spec)
        return json.dumps(
            {
                "chart_generated": True,
                "chart_type": spec.type,
                "title": spec.options.title,
                "columns": data.columns,
                "row_count": data.row_count,
            }
        )

    return {
        LIST_MODELS: list_models,
        QUERY_MODEL: query_model,
        NL_TO_SQL: nl_to_sql,
        NL_TO_CHART: nl_to_chart,
    }


class ChatResult(BaseModel):
    """The chat outcome: the answer, which tools ran, and any generated chart.

    ``chart`` is set when the assistant produced a chart via the ``nl_to_chart``
    tool (the latest one of the turn). The frontend renders it and offers to pin it
    to a dashboard (#12). ``None`` when no chart was generated.
    """

    answer: str
    tools_used: list[str]
    chart: ChartSpec | None = None


class ChatService:
    """Runs the grounded tool-dispatch loop for one chat turn."""

    def __init__(
        self,
        gateway: LLMGateway,
        handlers: dict[str, ToolHandler],
        *,
        max_turns: int = _MAX_TURNS,
        chart_sink: list[ChartSpec] | None = None,
    ) -> None:
        self._gateway = gateway
        self._handlers = handlers
        self._max_turns = max_turns
        # The same list the ``nl_to_chart`` handler appends to (per request). Defaults
        # to an empty list when no chart-producing handler is wired (e.g. unit tests).
        self._chart_sink: list[ChartSpec] = chart_sink if chart_sink is not None else []

    async def ask(self, ctx: TenantContext, message: str) -> ChatResult:
        """Answer ``message`` for the tenant via grounded tool-calling."""
        messages: list[ChatTurn] = [ChatTurn(role="user", text=message)]
        tools_used: list[str] = []

        for _ in range(self._max_turns):
            response = await self._gateway.complete_with_tools(
                ToolChatRequest(
                    system=SYSTEM_PROMPT, messages=messages, tools=TOOL_SPECS
                ),
                ctx=ctx,
            )
            if not response.tool_calls:
                answer = response.text or "I couldn't find an answer for that."
                return self._result(answer, tools_used)

            messages.append(
                ChatTurn(
                    role="assistant", text=response.text, tool_calls=response.tool_calls
                )
            )
            results: list[ToolResultMsg] = []
            for call in response.tool_calls:
                tools_used.append(call.name)
                content, is_error = await self._dispatch(ctx, call)
                results.append(
                    ToolResultMsg(tool_use_id=call.id, content=content, is_error=is_error)
                )
            messages.append(ChatTurn(role="user", tool_results=results))

        logger.info(
            "Chat hit max turns: tenant_id=%r tools_used=%r", ctx.tenant_id, tools_used
        )
        return self._result(
            "I couldn't complete that within the allowed number of steps.", tools_used
        )

    def _result(self, answer: str, tools_used: list[str]) -> ChatResult:
        """Assemble a ``ChatResult``, attaching the latest generated chart (if any)."""
        chart = self._chart_sink[-1] if self._chart_sink else None
        return ChatResult(answer=answer, tools_used=tools_used, chart=chart)

    async def _dispatch(self, ctx: TenantContext, call: ToolCall) -> tuple[str, bool]:
        """Execute one tool call, returning ``(result_text, is_error)`` (fail closed)."""
        handler = self._handlers.get(call.name)
        if handler is None:
            return (f"Unknown tool: {call.name}", True)
        try:
            return (await handler(ctx, call.input), False)
        except SemanticValidationError as exc:
            return (f"Error: {exc.reason}", True)
        except SQLValidationError as exc:
            return (f"Error: {exc.reason}", True)
        except ChartValidationError as exc:
            return (f"Error: could not build a valid chart ({exc}).", True)
        except (CubeAuthError, CubeQueryError):
            return ("The semantic layer is temporarily unavailable.", True)
        except ValueError as exc:
            # e.g. a malformed query request the model assembled — let it retry.
            return (f"Invalid tool input: {exc}", True)
        except Exception:  # fail closed; never leak internals to the model/user
            logger.exception(
                "Chat tool %r failed: tenant_id=%r", call.name, ctx.tenant_id
            )
            return ("That tool call failed unexpectedly.", True)


def get_chat_service(
    gateway: LLMGateway = Depends(get_llm_gateway),  # noqa: B008
    semantic: SemanticService = Depends(get_semantic_service),  # noqa: B008
    nl_sql: NLToSQLService = Depends(get_nl_to_sql_service),  # noqa: B008
    nl_chart: NLToChartService = Depends(get_nl_to_chart_service),  # noqa: B008
) -> ChatService:
    """FastAPI dependency: assemble a ``ChatService`` with grounded handlers.

    The per-request ``chart_sink`` is shared between the ``nl_to_chart`` handler and
    the service so a generated chart rides back on the reply (#12).
    """
    chart_sink: list[ChartSpec] = []
    handlers = build_handlers(semantic, nl_sql, nl_chart, chart_sink)
    return ChatService(gateway=gateway, handlers=handlers, chart_sink=chart_sink)
