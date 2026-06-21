"""Tests for the reusable agent runtime (#13) — fake gateway, no infra.

Mirrors the chat-loop guarantees at the framework level: the agent runs grounded
skills under the tenant context, feeds results back, returns the final answer, fails
closed on unknown/raising skills (without leaking internals), and is bounded by
max_turns. The SkillRegistry builds the provider-neutral specs + dispatch map.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.ai.agent import Agent, Skill, SkillRegistry
from app.ai.gateway.provider import ToolCall, ToolChatRequest, ToolChatResponse
from app.tenancy.context import TenantContext

_CTX = TenantContext(
    tenant_id="t1", iceberg_namespace="ns", clickhouse_db="db", dbt_schema="sch"
)


class _FakeGateway:
    def __init__(self, scripted: list[ToolChatResponse]) -> None:
        self._scripted = list(scripted)
        self.calls: list[ToolChatRequest] = []

    async def complete_with_tools(
        self, request: ToolChatRequest, *, ctx: TenantContext, model_override: str | None = None
    ) -> ToolChatResponse:
        self.calls.append(request)
        return self._scripted.pop(0)


def _skill(name: str, handler: Any) -> Skill:
    return Skill(name=name, description="desc", input_schema={"type": "object"}, handler=handler)


def _tool_call(name: str) -> ToolChatResponse:
    return ToolChatResponse(
        tool_calls=[ToolCall(id="tu1", name=name, input={})], stop_reason="tool_use"
    )


def _agent(gw: Any, skills: list[Skill], **kw: Any) -> Agent:
    return Agent(gw, SkillRegistry(skills), system="sys", **kw)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_runs_skill_under_tenant_ctx_then_answers() -> None:
    gw = _FakeGateway([_tool_call("greet"), ToolChatResponse(text="hi", stop_reason="end_turn")])
    seen: dict[str, Any] = {}

    async def greet(ctx: TenantContext, _inp: dict[str, Any]) -> str:
        seen["ctx"] = ctx
        return "greeted"

    result = await _agent(gw, [_skill("greet", greet)]).run(_CTX, "hello")

    assert result.answer == "hi"
    assert result.tools_used == ["greet"]
    assert seen["ctx"].clickhouse_db == "db"
    assert gw.calls[1].messages[-1].tool_results[0].content == "greeted"


@pytest.mark.asyncio
async def test_unknown_skill_is_returned_as_error() -> None:
    gw = _FakeGateway([_tool_call("nope"), ToolChatResponse(text="can't", stop_reason="end_turn")])
    result = await _agent(gw, []).run(_CTX, "x")
    assert result.answer == "can't"
    err = gw.calls[1].messages[-1].tool_results[0]
    assert err.is_error is True
    assert "Unknown tool" in err.content


@pytest.mark.asyncio
async def test_raising_skill_fails_closed() -> None:
    gw = _FakeGateway([_tool_call("boom"), ToolChatResponse(text="done", stop_reason="end_turn")])

    async def boom(ctx: TenantContext, _inp: dict[str, Any]) -> str:
        raise RuntimeError("secret internal detail")

    result = await _agent(gw, [_skill("boom", boom)]).run(_CTX, "x")
    assert result.answer == "done"
    err = gw.calls[1].messages[-1].tool_results[0]
    assert err.is_error is True
    assert "secret" not in err.content  # internals never leak


@pytest.mark.asyncio
async def test_bounded_by_max_turns() -> None:
    gw = _FakeGateway([_tool_call("greet") for _ in range(10)])

    async def greet(ctx: TenantContext, _inp: dict[str, Any]) -> str:
        return "g"

    result = await _agent(gw, [_skill("greet", greet)], max_turns=3).run(_CTX, "x")
    assert "allowed number of steps" in result.answer
    assert len(gw.calls) == 3


def test_registry_builds_specs_and_handlers() -> None:
    async def handler(ctx: TenantContext, _inp: dict[str, Any]) -> str:
        return "ok"

    registry = SkillRegistry([_skill("alpha", handler), _skill("beta", handler)])
    names = {s.name for s in registry.tool_specs()}
    assert names == {"alpha", "beta"}
    assert set(registry.handlers()) == {"alpha", "beta"}
