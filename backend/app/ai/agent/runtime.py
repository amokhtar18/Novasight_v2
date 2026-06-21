"""Reusable agent runtime: skills + a grounded tool-dispatch loop (#13).

This generalises the chat tool-loop into a small framework the AI features share:

* **Skill** — a named, JSON-schema'd capability backed by an async handler that
  delegates to an existing, already-validated service (golden rule #3: skills only
  reach the governed semantic layer / validated NL→SQL, never raw tables).
* **SkillRegistry** — assembles the provider-neutral ``ToolSpec`` list + the dispatch
  map from a set of skills.
* **Agent** — runs the bounded loop: send the conversation + skills to the gateway;
  if the model called skills, execute each under the tenant context and feed the
  results back; otherwise return the final answer. Fail-closed: a skill error is
  returned to the model as an ``is_error`` result, never crashing the request.

Instructions/prompts are passed in (loaded from the versioned prompt dir by the
caller), so the runtime itself hardcodes nothing. Both the legacy chat surface and
the unified assistant build an ``Agent`` from a registry; the only thing that differs
is the skill set + system instruction.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.ai.gateway import LLMGateway
from app.ai.gateway.provider import (
    ChatTurn,
    ToolCall,
    ToolChatRequest,
    ToolResultMsg,
    ToolSpec,
)
from app.ai.nl_chart import ChartValidationError
from app.ai.nl_sql import SQLValidationError
from app.ai.semantic.client import CubeAuthError, CubeQueryError
from app.services.semantic import SemanticValidationError
from app.tenancy.context import TenantContext

logger = logging.getLogger(__name__)

# A skill handler: given the tenant ctx + the model's input, return result text.
SkillHandler = Callable[[TenantContext, dict[str, Any]], Awaitable[str]]

# Hard cap on loop iterations — bounds cost + prevents runaway tool loops.
DEFAULT_MAX_TURNS = 6


@dataclass(frozen=True)
class Skill:
    """One capability the agent may call: name, description, JSON-schema, handler."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: SkillHandler


class SkillRegistry:
    """A set of skills → the provider-neutral tool specs + dispatch map."""

    def __init__(self, skills: list[Skill]) -> None:
        self._skills = {s.name: s for s in skills}

    def tool_specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(name=s.name, description=s.description, input_schema=s.input_schema)
            for s in self._skills.values()
        ]

    def handlers(self) -> dict[str, SkillHandler]:
        return {name: s.handler for name, s in self._skills.items()}


class AgentResult(BaseModel):
    """The outcome of one agent turn: the answer + which skills ran."""

    answer: str
    tools_used: list[str]


class Agent:
    """Runs a bounded, grounded skill-dispatch loop for one user message."""

    def __init__(
        self,
        gateway: LLMGateway,
        registry: SkillRegistry,
        *,
        system: str,
        max_turns: int = DEFAULT_MAX_TURNS,
    ) -> None:
        self._gateway = gateway
        self._system = system
        self._specs = registry.tool_specs()
        self._handlers = registry.handlers()
        self._max_turns = max_turns

    async def run(self, ctx: TenantContext, message: str) -> AgentResult:
        """Answer ``message`` for the tenant via grounded skill-calling."""
        messages: list[ChatTurn] = [ChatTurn(role="user", text=message)]
        tools_used: list[str] = []

        for _ in range(self._max_turns):
            response = await self._gateway.complete_with_tools(
                ToolChatRequest(system=self._system, messages=messages, tools=self._specs),
                ctx=ctx,
            )
            if not response.tool_calls:
                answer = response.text or "I couldn't find an answer for that."
                return AgentResult(answer=answer, tools_used=tools_used)

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
            "Agent hit max turns: tenant_id=%r tools_used=%r", ctx.tenant_id, tools_used
        )
        return AgentResult(
            answer="I couldn't complete that within the allowed number of steps.",
            tools_used=tools_used,
        )

    async def _dispatch(self, ctx: TenantContext, call: ToolCall) -> tuple[str, bool]:
        """Execute one skill call, returning ``(result_text, is_error)`` (fail closed)."""
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
            return (f"Invalid tool input: {exc}", True)
        except Exception:  # fail closed; never leak internals to the model/user
            logger.exception("Skill %r failed: tenant_id=%r", call.name, ctx.tenant_id)
            return ("That tool call failed unexpectedly.", True)
