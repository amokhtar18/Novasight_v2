"""LLM gateway facade and FastAPI dependency wiring.

``LLMGateway`` is the single entry point for all LLM calls in ``app/ai/``.
It:
1. Resolves the effective model via ``model_for_tenant()``.
2. Fills in default generation parameters from settings.
3. Dispatches to the configured ``LLMProvider``.
4. Logs the call with tenant context but without secrets or PII.

Provider model selection
------------------------
The effective model for every request is resolved as follows::

    model_for_tenant(ctx, ai_settings=..., override=None)
    └── if override is not None  → use override
    └── else                     → use settings.ai.model

This is the plug-in point for a future per-tenant model-config lookup: replace
the body of ``model_for_tenant`` with a database lookup keyed on
``ctx.tenant_id``.  All callers already thread the ``TenantContext`` through, so
no API change is required.

Lifespan
--------
``close_llm_client()`` must be called during FastAPI lifespan shutdown to
release the provider's HTTP connection pool.  Wire it alongside the existing
``close_http_client()`` from the semantic layer::

    # app/main.py lifespan shutdown
    await close_llm_client()
"""
from __future__ import annotations

import logging

from fastapi import Depends

from app.ai.gateway.provider import LLMProvider, LLMRequest, LLMResponse
from app.ai.gateway.registry import build_provider
from app.core.config import AISettings, Settings, get_settings
from app.tenancy.context import TenantContext

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Process-wide provider singleton
# ---------------------------------------------------------------------------

_provider: LLMProvider | None = None


def _get_provider(ai_settings: AISettings) -> LLMProvider:
    """Return the process-wide shared ``LLMProvider``.

    Created lazily on first call from the configured settings.  Tests bypass this
    by constructing ``LLMGateway`` directly with a mock provider.
    """
    global _provider
    if _provider is None:
        _provider = build_provider(ai_settings)
    return _provider


async def close_llm_client() -> None:
    """Close the process-wide provider's HTTP client.

    Wire into the FastAPI lifespan shutdown (analogous to
    ``app.ai.semantic.client.close_http_client``).  Idempotent — a no-op if the
    provider was never instantiated (e.g. a process that received no AI requests).
    """
    global _provider
    if _provider is not None:
        await _provider.close()
        _provider = None


# ---------------------------------------------------------------------------
# Per-tenant model resolver
# ---------------------------------------------------------------------------


def model_for_tenant(
    ctx: TenantContext,
    *,
    ai_settings: AISettings,
    override: str | None = None,
) -> str:
    """Return the effective model id for a tenant request.

    Resolution order:
    1. ``override`` if explicitly supplied (non-None) — the caller/tenant has
       requested a specific model (e.g. from a future per-tenant config record).
    2. ``ai_settings.model`` — the deployment-wide default from ``AI__MODEL``.

    This is the designated plug-in point for a future per-tenant model-config
    lookup.  When that feature lands, replace the ``ai_settings.model`` fallback
    with a database lookup keyed on ``ctx.tenant_id``.  All callers already thread
    the ``TenantContext`` through, so no API change is required.

    ``ai_settings`` is a REQUIRED injected dependency — the function never reads
    the global ``get_settings()`` cache. Callers thread the same ``AISettings``
    instance the request resolved at the boundary, keeping model selection
    deterministic and honouring the injected-settings discipline.

    Args:
        ctx: The server-resolved tenant context.  Currently used only for
            logging; it will be the lookup key when per-tenant config lands.
        ai_settings: The ``AISettings`` instance to read the default model from
            (env var ``AI__MODEL``).
        override: An explicit model id supplied by the caller (e.g. from a
            validated API parameter).  Pass ``None`` to use the default.

    Returns:
        The model id string to use for this request.
    """
    if override is not None:
        logger.debug(
            "model_for_tenant: tenant_id=%r using override model=%r",
            ctx.tenant_id,
            override,
        )
        return override
    model = ai_settings.model
    logger.debug(
        "model_for_tenant: tenant_id=%r using default model=%r",
        ctx.tenant_id,
        model,
    )
    return model


# ---------------------------------------------------------------------------
# Gateway facade
# ---------------------------------------------------------------------------


class LLMGateway:
    """Provider-agnostic LLM facade.

    Callers supply an ``LLMRequest`` (system + user_message) and a
    ``TenantContext``.  The gateway resolves the effective model, fills in
    default generation params from settings, and dispatches to the provider.

    The ``TenantContext`` is used to scope logging and as the future hook for
    per-tenant model selection — it is never forwarded to the provider.

    Args:
        provider: Any ``LLMProvider`` implementation.
        ai_settings: The ``AISettings`` group from application settings.
    """

    def __init__(self, provider: LLMProvider, ai_settings: AISettings) -> None:
        self._provider = provider
        self._settings = ai_settings

    async def complete(
        self,
        request: LLMRequest,
        *,
        ctx: TenantContext,
        model_override: str | None = None,
    ) -> LLMResponse:
        """Complete a request using the configured provider.

        Resolves the effective model via ``model_for_tenant()``, fills default
        temperature and max_tokens from settings, then calls the provider.

        Args:
            request: The LLM request.  ``model``, ``temperature``, and
                ``max_tokens`` may be ``None``; this method fills them from
                settings before forwarding.
            ctx: Server-resolved tenant context (used for logging + future
                per-tenant model resolution).
            model_override: Optional per-request model id.  Forwarded to
                ``model_for_tenant()`` as the ``override`` parameter.

        Returns:
            A typed ``LLMResponse``.

        Raises:
            LLMProviderError: Propagated from the provider on any failure.
        """
        effective_model = model_for_tenant(
            ctx,
            override=model_override or request.model,
            ai_settings=self._settings,
        )
        effective_temperature = (
            request.temperature
            if request.temperature is not None
            else self._settings.temperature
        )
        effective_max_tokens = (
            request.max_tokens
            if request.max_tokens is not None
            else self._settings.max_tokens
        )

        resolved_request = request.model_copy(
            update={
                "model": effective_model,
                "temperature": effective_temperature,
                "max_tokens": effective_max_tokens,
            }
        )

        logger.info(
            "LLMGateway.complete tenant_id=%r model=%r temperature=%s max_tokens=%d",
            ctx.tenant_id,
            effective_model,
            effective_temperature,
            effective_max_tokens,
        )

        response = await self._provider.complete(resolved_request)

        logger.info(
            "LLMGateway.complete done tenant_id=%r model=%r "
            "input_tokens=%d output_tokens=%d",
            ctx.tenant_id,
            response.model,
            response.usage.get("input_tokens", 0),
            response.usage.get("output_tokens", 0),
        )

        return response


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


def get_llm_gateway(
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> LLMGateway:
    """FastAPI dependency: return an ``LLMGateway`` wired from settings.

    Reuses the process-wide provider singleton (one HTTP client for the lifetime
    of the process).  Override in tests via ``app.dependency_overrides`` or
    construct ``LLMGateway`` directly with a mock provider.

    Example::

        @router.post("/ask")
        async def ask(
            ctx: TenantContext = Depends(get_tenant_context),
            gateway: LLMGateway = Depends(get_llm_gateway),
        ) -> str:
            resp = await gateway.complete(
                LLMRequest(system="You are a helpful analyst.", user_message="…"),
                ctx=ctx,
            )
            return resp.text
    """
    return LLMGateway(
        provider=_get_provider(settings.ai),
        ai_settings=settings.ai,
    )
