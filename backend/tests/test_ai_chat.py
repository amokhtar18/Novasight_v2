"""Tests for the chat tool-dispatch loop (#11) — fake gateway, no infra.

Verifies the loop runs grounded tools under the tenant context, feeds results back,
returns the model's final answer, fails closed on unknown/raising tools (without
crashing), and is bounded by max_turns. The live LLM tool-calling + provider
adapters are stack-verified; this exercises the orchestration that's ours.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.ai.chat.service import ChatService
from app.ai.gateway.provider import ToolCall, ToolChatRequest, ToolChatResponse
from app.tenancy.context import TenantContext

_CTX = TenantContext(
    tenant_id="t1", iceberg_namespace="ns", clickhouse_db="db", dbt_schema="sch"
)


class _FakeGateway:
    """Returns scripted ToolChatResponses and records the requests it received."""

    def __init__(self, scripted: list[ToolChatResponse]) -> None:
        self._scripted = list(scripted)
        self.calls: list[ToolChatRequest] = []

    async def complete_with_tools(
        self, request: ToolChatRequest, *, ctx: TenantContext, model_override: str | None = None
    ) -> ToolChatResponse:
        self.calls.append(request)
        return self._scripted.pop(0)


def _tool_call(name: str) -> ToolChatResponse:
    return ToolChatResponse(
        tool_calls=[ToolCall(id="tu1", name=name, input={})], stop_reason="tool_use"
    )


@pytest.mark.asyncio
async def test_executes_tool_under_tenant_ctx_then_answers() -> None:
    gw = _FakeGateway(
        [
            _tool_call("list_semantic_models"),
            ToolChatResponse(text="You have a regional_sales model.", stop_reason="end_turn"),
        ]
    )
    seen: dict[str, Any] = {}

    async def list_models(ctx: TenantContext, _inp: dict[str, Any]) -> str:
        seen["ctx"] = ctx
        return '[{"name": "regional_sales"}]'

    svc = ChatService(gw, {"list_semantic_models": list_models})  # type: ignore[arg-type]
    result = await svc.ask(_CTX, "what can I ask about?")

    assert result.answer == "You have a regional_sales model."
    assert result.tools_used == ["list_semantic_models"]
    # The tool ran under the server-resolved tenant context.
    assert seen["ctx"].clickhouse_db == "db"
    # Second round-trip carried the tool result back to the model.
    assert len(gw.calls) == 2
    assert gw.calls[1].messages[-1].tool_results[0].content == '[{"name": "regional_sales"}]'


@pytest.mark.asyncio
async def test_unknown_tool_is_returned_as_error_and_recovers() -> None:
    gw = _FakeGateway(
        [
            _tool_call("nonexistent"),
            ToolChatResponse(text="I can't do that.", stop_reason="end_turn"),
        ]
    )
    svc = ChatService(gw, {})  # no handlers registered
    result = await svc.ask(_CTX, "x")

    assert result.answer == "I can't do that."
    err = gw.calls[1].messages[-1].tool_results[0]
    assert err.is_error is True
    assert "Unknown tool" in err.content


@pytest.mark.asyncio
async def test_raising_handler_fails_closed() -> None:
    gw = _FakeGateway(
        [_tool_call("boom"), ToolChatResponse(text="done", stop_reason="end_turn")]
    )

    async def boom(ctx: TenantContext, _inp: dict[str, Any]) -> str:
        raise RuntimeError("kaboom — should not surface")

    svc = ChatService(gw, {"boom": boom})  # type: ignore[arg-type]
    result = await svc.ask(_CTX, "x")

    assert result.answer == "done"
    err = gw.calls[1].messages[-1].tool_results[0]
    assert err.is_error is True
    assert "kaboom" not in err.content  # internal detail not leaked


@pytest.mark.asyncio
async def test_bounded_by_max_turns() -> None:
    # Model always asks for a tool → the loop must stop at max_turns.
    gw = _FakeGateway([_tool_call("list_semantic_models") for _ in range(10)])

    async def list_models(ctx: TenantContext, _inp: dict[str, Any]) -> str:
        return "[]"

    svc = ChatService(gw, {"list_semantic_models": list_models}, max_turns=3)  # type: ignore[arg-type]
    result = await svc.ask(_CTX, "x")

    assert "allowed number of steps" in result.answer
    assert len(gw.calls) == 3
