"""Anthropic Claude provider for the LLM gateway.

Implements the ``LLMProvider`` protocol using the official ``anthropic`` Python SDK
(``AsyncAnthropic`` + the Messages API).

Security guarantees
-------------------
- The API key is read via ``SecretStr.get_secret_value()`` exactly once, inline
  in the constructor, and is never stored in any named attribute or local variable
  that could appear in a traceback, ``repr()``, or log record.
- Error messages passed to ``LLMProviderError`` contain only the HTTP status code
  and a generic label — never the API key, request body, or tenant data.
- Logging at this layer uses only the model name and token counts; no prompt text,
  no API key, no tenant IDs (the gateway layer adds tenant tags above this).

Configuration
-------------
All parameters come from the ``AISettings`` group (injected at construction time):
``model``, ``temperature``, ``max_tokens``, and ``api_key``.  Nothing is hardcoded.

Usage
-----
Instantiate once and share the instance across requests (the underlying SDK client
maintains a connection pool internally).  Call ``close()`` during lifespan shutdown.

Example (for illustration; runtime model always comes from settings)::

    # The model "claude-opus-4-8" below is only shown here as an illustration.
    # The running system reads the model from AI__MODEL — never from code.
    settings = AISettings(
        provider="anthropic",
        model="claude-opus-4-8",    # illustration only — real value from AI__MODEL
        api_key=SecretStr("sk-ant-…"),
        temperature=0.0,
        max_tokens=1024,
        prompt_template_dir="/path/to/your/prompts",  # illustration — from AI__PROMPT_TEMPLATE_DIR
    )
    provider = AnthropicProvider(settings)
    response = await provider.complete(request)
    await provider.close()
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

import anthropic

if TYPE_CHECKING:
    from anthropic.types import MessageParam, ToolParam

from app.ai.gateway.provider import (
    LLMProviderError,
    LLMRequest,
    LLMResponse,
    ToolCall,
    ToolChatRequest,
    ToolChatResponse,
)
from app.core.config import AISettings

logger = logging.getLogger(__name__)


class AnthropicProvider:
    """``LLMProvider`` implementation backed by the Anthropic Messages API.

    The ``AsyncAnthropic`` client is created once at construction and reused for
    all calls.  The API key is accessed inline via ``get_secret_value()`` and is
    never stored in a named attribute.

    Args:
        ai_settings: The ``AISettings`` group from application settings.  All
            generation parameters and the API key are read from here.
    """

    #: Provider name for error messages and registry lookups.
    PROVIDER_NAME = "anthropic"

    def __init__(self, ai_settings: AISettings) -> None:
        # get_secret_value() is called inline — the result is not bound to a named
        # variable so it cannot appear in local-variable dumps or tracebacks.
        self._client = anthropic.AsyncAnthropic(
            api_key=ai_settings.api_key.get_secret_value(),
        )
        # Store only non-secret generation defaults for use as fallbacks.
        self._default_temperature = ai_settings.temperature
        self._default_max_tokens = ai_settings.max_tokens

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Call the Anthropic Messages API and return a typed response.

        The ``request.model``, ``request.temperature``, and ``request.max_tokens``
        are expected to be fully resolved by the gateway before this method is
        called (model is required; params fall back to construction defaults if
        still None).

        Args:
            request: A fully resolved ``LLMRequest``.

        Returns:
            A typed ``LLMResponse`` with text, model, and usage.

        Raises:
            LLMProviderError: On any Anthropic SDK error (auth, rate limit, network,
                content policy, etc.).
        """
        model = request.model or ""
        temperature = (
            request.temperature
            if request.temperature is not None
            else self._default_temperature
        )
        max_tokens = (
            request.max_tokens
            if request.max_tokens is not None
            else self._default_max_tokens
        )

        logger.debug(
            "AnthropicProvider.complete model=%r temperature=%s max_tokens=%d",
            model,
            temperature,
            max_tokens,
        )

        try:
            message = await self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=request.system,
                messages=[{"role": "user", "content": request.user_message}],
            )
        except anthropic.AuthenticationError as exc:
            # Do NOT include exc details in the message — they may contain the key.
            raise LLMProviderError(
                "Anthropic authentication failed — check AI__API_KEY",
                provider=self.PROVIDER_NAME,
                status_code=401,
            ) from exc
        except anthropic.RateLimitError as exc:
            raise LLMProviderError(
                "Anthropic rate limit exceeded",
                provider=self.PROVIDER_NAME,
                status_code=429,
            ) from exc
        except anthropic.APIStatusError as exc:
            raise LLMProviderError(
                f"Anthropic API error: HTTP {exc.status_code}",
                provider=self.PROVIDER_NAME,
                status_code=exc.status_code,
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise LLMProviderError(
                "Anthropic connection error",
                provider=self.PROVIDER_NAME,
            ) from exc

        # Extract the text from the first ContentBlock (Messages API guarantee).
        text = ""
        for block in message.content:
            if block.type == "text":
                text = block.text.strip()
                break

        usage: dict[str, int] = {}
        if message.usage is not None:
            usage = {
                "input_tokens": message.usage.input_tokens,
                "output_tokens": message.usage.output_tokens,
            }

        raw_metadata: dict[str, Any] = {
            "stop_reason": message.stop_reason,
        }

        logger.debug(
            "AnthropicProvider.complete done model=%r input_tokens=%d output_tokens=%d",
            message.model,
            usage.get("input_tokens", 0),
            usage.get("output_tokens", 0),
        )

        return LLMResponse(
            text=text,
            model=message.model,
            usage=usage,
            raw_metadata=raw_metadata,
        )

    async def complete_with_tools(self, request: ToolChatRequest) -> ToolChatResponse:
        """Run a tool-enabled, multi-turn completion via the Messages API.

        Maps the provider-neutral turns/tools onto Anthropic's ``tool_use`` /
        ``tool_result`` content blocks (see the ``claude-api`` skill), then parses
        the response back into neutral ``ToolCall`` objects. Sampling params are
        intentionally omitted — current Claude 4.x models reject them.

        This adapter is exercised against the live stack; the chat dispatch loop in
        ``app/ai/chat`` is what's unit-tested (with a fake gateway).
        """
        model = request.model or ""
        max_tokens = (
            request.max_tokens if request.max_tokens is not None else self._default_max_tokens
        )
        tools = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in request.tools
        ]
        messages = [self._to_anthropic_message(turn) for turn in request.messages]

        try:
            message = await self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=request.system,
                # The dicts are built to the Messages API shape; cast at this SDK
                # boundary (the provider is the only layer allowed to touch SDK types).
                messages=cast("list[MessageParam]", messages),
                tools=cast("list[ToolParam]", tools),
            )
        except anthropic.AuthenticationError as exc:
            raise LLMProviderError(
                "Anthropic authentication failed — check AI__API_KEY",
                provider=self.PROVIDER_NAME,
                status_code=401,
            ) from exc
        except anthropic.RateLimitError as exc:
            raise LLMProviderError(
                "Anthropic rate limit exceeded",
                provider=self.PROVIDER_NAME,
                status_code=429,
            ) from exc
        except anthropic.APIStatusError as exc:
            raise LLMProviderError(
                f"Anthropic API error: HTTP {exc.status_code}",
                provider=self.PROVIDER_NAME,
                status_code=exc.status_code,
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise LLMProviderError(
                "Anthropic connection error",
                provider=self.PROVIDER_NAME,
            ) from exc

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in message.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, input=dict(block.input or {}))
                )

        usage: dict[str, int] = {}
        if message.usage is not None:
            usage = {
                "input_tokens": message.usage.input_tokens,
                "output_tokens": message.usage.output_tokens,
            }

        return ToolChatResponse(
            text="".join(text_parts).strip(),
            tool_calls=tool_calls,
            stop_reason=message.stop_reason or "",
            model=message.model,
            usage=usage,
        )

    @staticmethod
    def _to_anthropic_message(turn: Any) -> dict[str, Any]:  # noqa: ANN401 — ChatTurn
        """Map a neutral ``ChatTurn`` to an Anthropic message dict."""
        if turn.role == "assistant":
            content: list[dict[str, Any]] = []
            if turn.text:
                content.append({"type": "text", "text": turn.text})
            for call in turn.tool_calls:
                content.append(
                    {"type": "tool_use", "id": call.id, "name": call.name, "input": call.input}
                )
            return {"role": "assistant", "content": content}
        # user turn — either tool results or plain text
        if turn.tool_results:
            return {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": r.tool_use_id,
                        "content": r.content,
                        "is_error": r.is_error,
                    }
                    for r in turn.tool_results
                ],
            }
        return {"role": "user", "content": turn.text or ""}

    async def close(self) -> None:
        """Close the underlying ``AsyncAnthropic`` HTTP client.

        Uses the SDK's public async ``close()`` (not the private ``__aexit__``),
        so an SDK minor-version bump can't silently break teardown. Idempotent.
        """
        await self._client.close()
