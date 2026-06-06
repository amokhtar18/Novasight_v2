"""LLM gateway sub-package (Phase 4, Task 4.2).

Provides a provider-agnostic interface for LLM completions used by all AI features
in NovaSight. The gateway is the single entry point: callers never import or reference
provider-specific types.

Public surface
--------------
- ``LLMProvider``        — the abstract protocol every provider implements.
- ``LLMRequest``         — typed request carrying system prompt, messages, and generation params.
- ``LLMResponse``        — typed response carrying generated text and token usage.
- ``LLMGateway``         — the facade that selects the right provider and dispatches calls.
- ``model_for_tenant``   — resolver that returns the effective model id for a request.
- ``get_llm_gateway``    — FastAPI dependency (wired from settings).
- ``close_llm_client``   — lifespan shutdown hook (release provider HTTP connections).
- ``PromptLoader``       — versioned prompt-template loader.
- ``get_prompt_loader``  — FastAPI dependency for the prompt loader.

Usage in a FastAPI endpoint::

    from app.ai.gateway import get_llm_gateway, LLMGateway, LLMRequest
    from app.tenancy.context import TenantContext, get_tenant_context

    @router.post("/ask")
    async def ask(
        ctx: TenantContext = Depends(get_tenant_context),
        gateway: LLMGateway = Depends(get_llm_gateway),
    ) -> str:
        resp = await gateway.complete(
            LLMRequest(
                system="You are a helpful analyst.",
                user_message="Summarise revenue trends.",
            ),
            ctx=ctx,
        )
        return resp.text
"""
from app.ai.gateway.gateway import (
    LLMGateway,
    close_llm_client,
    get_llm_gateway,
    model_for_tenant,
)
from app.ai.gateway.loader import PromptLoader, get_prompt_loader
from app.ai.gateway.provider import LLMProvider, LLMRequest, LLMResponse

__all__ = [
    "LLMGateway",
    "LLMProvider",
    "LLMRequest",
    "LLMResponse",
    "PromptLoader",
    "close_llm_client",
    "get_llm_gateway",
    "get_prompt_loader",
    "model_for_tenant",
]
