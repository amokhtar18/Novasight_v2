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
from app.ai.nl_sql import NLToSQLService, SQLValidationError, get_nl_to_sql_service
from app.ai.semantic.client import CubeAuthError, CubeQueryError
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

SYSTEM_PROMPT = (
    "You are NovaSight's analytics assistant. Answer questions about the tenant's "
    "data ONLY by calling the provided tools, which query a governed semantic layer. "
    "Never invent numbers, table names, or columns. First call list_semantic_models "
    "to discover the available measures and dimensions, then query_semantic_model "
    "with fully-qualified names, or nl_to_sql for ad-hoc questions. If the tools "
    "cannot answer, say so plainly. Base every figure you state on a tool result."
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
]


def build_handlers(
    semantic: SemanticService, nl_sql: NLToSQLService
) -> dict[str, ToolHandler]:
    """Wire the grounded tool handlers from the existing services."""

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

    return {LIST_MODELS: list_models, QUERY_MODEL: query_model, NL_TO_SQL: nl_to_sql}


class ChatResult(BaseModel):
    """The chat outcome: the assistant's answer + which tools were called."""

    answer: str
    tools_used: list[str]


class ChatService:
    """Runs the grounded tool-dispatch loop for one chat turn."""

    def __init__(
        self,
        gateway: LLMGateway,
        handlers: dict[str, ToolHandler],
        *,
        max_turns: int = _MAX_TURNS,
    ) -> None:
        self._gateway = gateway
        self._handlers = handlers
        self._max_turns = max_turns

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
                return ChatResult(answer=answer, tools_used=tools_used)

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
        return ChatResult(
            answer="I couldn't complete that within the allowed number of steps.",
            tools_used=tools_used,
        )

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
) -> ChatService:
    """FastAPI dependency: assemble a ``ChatService`` with grounded handlers."""
    return ChatService(gateway=gateway, handlers=build_handlers(semantic, nl_sql))
