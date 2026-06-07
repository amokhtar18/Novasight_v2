"""Provider-agnostic LLM interface.

Every concrete LLM provider (Anthropic, OpenAI, Azure, …) must implement the
``LLMProvider`` protocol.  Callers in ``app/ai/`` only ever import and reference
these types — they must never import or reference provider-specific SDK types.

Design notes
------------
- The protocol uses ``runtime_checkable`` so instances can be validated with
  ``isinstance`` at the factory/registry level without requiring ABC inheritance.
- ``LLMRequest`` is a plain Pydantic model.  The gateway fills ``model`` from
  ``model_for_tenant()`` before calling the provider, so callers may omit it.
- ``LLMResponse`` carries the generated ``text`` plus a ``usage`` dict for
  structured logging / cost tracking.  The dict is untyped (``dict[str, int]``)
  because different providers return different usage keys; callers that need
  specific counts should key by convention (``"input_tokens"``, ``"output_tokens"``).
"""
from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class LLMRequest(BaseModel):
    """Structured request to an LLM provider.

    ``model`` is intentionally optional here: the gateway resolves the effective
    model from ``model_for_tenant()`` and injects it before forwarding to the
    provider, so most callers can omit it.

    Args:
        system: The system-role instruction sent before the conversation.
        user_message: The user-turn message for this request.
        model: Optional model override (resolved by the gateway if absent).
        temperature: Sampling temperature (0.0 = deterministic, 1.0 = creative).
            When ``None`` the gateway substitutes ``settings.ai.temperature``.
        max_tokens: Maximum tokens to generate.  When ``None`` the gateway
            substitutes ``settings.ai.max_tokens``.
    """

    system: str
    user_message: str
    model: str | None = Field(default=None)
    temperature: float | None = Field(default=None)
    max_tokens: int | None = Field(default=None)


class LLMResponse(BaseModel):
    """Typed response from an LLM provider.

    Args:
        text: The generated completion text (stripped of leading/trailing whitespace).
        model: The model id that actually generated the response (echoed from the
            provider response, not the request, so it reflects the true value).
        usage: Token usage reported by the provider.  Keys follow the convention
            ``"input_tokens"`` and ``"output_tokens"`` regardless of provider.
        raw_metadata: Any additional provider-specific metadata (e.g. stop reason).
            Stored as an opaque dict so callers can log/inspect it without
            depending on provider types.
    """

    text: str
    model: str
    usage: dict[str, int] = Field(default_factory=dict)
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Tool-use (multi-turn) types — provider-neutral (used by the AI chat surface).
#
# These mirror the tool-use shape every major provider supports (Anthropic
# tool_use/tool_result, OpenAI tool_calls/tool messages) without leaking any
# provider type. The chat service builds the request, runs the dispatch loop, and
# feeds tool results back as ``ChatTurn``s with ``tool_results``.
# ---------------------------------------------------------------------------


class ToolSpec(BaseModel):
    """A tool the model may call: name, description, and a JSON-Schema input."""

    name: str
    description: str
    input_schema: dict[str, Any]


class ToolCall(BaseModel):
    """A model's request to call a tool (one tool_use)."""

    id: str
    name: str
    input: dict[str, Any] = Field(default_factory=dict)


class ToolResultMsg(BaseModel):
    """The result of executing one tool call, fed back to the model."""

    tool_use_id: str
    content: str
    is_error: bool = False


class ChatTurn(BaseModel):
    """One conversation turn. Assistant turns may carry ``tool_calls``; a user
    turn returning tool output carries ``tool_results`` (and usually no text)."""

    role: Literal["user", "assistant"]
    text: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_results: list[ToolResultMsg] = Field(default_factory=list)


class ToolChatRequest(BaseModel):
    """A tool-enabled, multi-turn completion request."""

    system: str
    messages: list[ChatTurn]
    tools: list[ToolSpec] = Field(default_factory=list)
    model: str | None = None
    max_tokens: int | None = None


class ToolChatResponse(BaseModel):
    """The model's reply: any text plus the tool calls it wants executed.

    ``stop_reason == "tool_use"`` (with a non-empty ``tool_calls``) means the
    caller must run the tools and continue the loop; ``"end_turn"`` means done.
    """

    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    stop_reason: str = ""
    model: str = ""
    usage: dict[str, int] = Field(default_factory=dict)


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol every LLM provider must satisfy.

    Providers are constructed once (at gateway init time) and reuse an internal
    async client for the lifetime of the process.  The ``complete`` method is the
    only public surface.

    The provider must NOT:
    - Accept or store the API key in any attribute accessible after construction.
    - Log the API key, the full request, or any PII from the tenant.
    - Raise provider-specific exception types — wrap them in ``LLMProviderError``.
    """

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Send *request* to the underlying model and return a typed response.

        The ``request.model``, ``request.temperature``, and ``request.max_tokens``
        are all filled by the gateway before this method is called — providers may
        treat them as required/non-None.

        Args:
            request: A fully resolved ``LLMRequest`` (model + params populated).

        Returns:
            A typed ``LLMResponse``.

        Raises:
            LLMProviderError: On any provider-side failure (network, auth, rate
                limit, etc.).  The original exception is chained via ``__cause__``
                for structured logging but must not propagate provider-specific types.
        """
        ...

    async def complete_with_tools(self, request: ToolChatRequest) -> ToolChatResponse:
        """Run a tool-enabled, multi-turn completion and return the model's reply.

        The reply carries any assistant text plus the tool calls the model wants
        executed (``stop_reason == "tool_use"``). The caller (chat service) runs
        the tools and continues the loop by appending a ``ChatTurn`` with
        ``tool_results``. ``model``/``max_tokens`` are filled by the gateway.

        Raises:
            LLMProviderError: On any provider-side failure (wrapped, never leaking
                provider-specific types).
        """
        ...

    async def close(self) -> None:
        """Release any resources held by this provider (HTTP clients, etc.).

        Called during the FastAPI lifespan shutdown.  Must be idempotent.
        """
        ...


class LLMProviderError(Exception):
    """Raised by a provider when the LLM call fails for any reason.

    The message is safe to log but must never include the API key or tenant PII.
    The original exception is available via ``__cause__`` for structured logging.

    Args:
        message: Human-readable error summary (safe to log and surface to callers).
        provider: The provider name (e.g. ``"anthropic"``).
        status_code: HTTP status code, if the failure was an HTTP error.
    """

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
