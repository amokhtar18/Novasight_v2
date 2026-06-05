"""Provider registry: maps ``settings.ai.provider`` strings to factory callables.

Adding a new provider
---------------------
1. Create ``providers/<name>.py`` implementing the ``LLMProvider`` protocol.
2. Import its class and add one line to ``_REGISTRY`` below.
3. No other file requires modification — callers access providers through
   ``build_provider()`` only.

Fail-closed
-----------
An unknown ``provider`` string raises ``ValueError`` at startup (before any request
is served), so a misconfigured deployment is caught early, not at request time.
"""
from __future__ import annotations

from collections.abc import Callable

from app.ai.gateway.provider import LLMProvider
from app.core.config import AISettings

# Type alias: a factory that receives AISettings and returns an LLMProvider.
ProviderFactory = Callable[[AISettings], LLMProvider]


def _anthropic_factory(ai_settings: AISettings) -> LLMProvider:
    from app.ai.gateway.providers.anthropic import AnthropicProvider

    return AnthropicProvider(ai_settings)


# Registry: provider name → factory callable.
# Import lazily (inside the factory) so unknown providers don't import their
# optional SDK at startup — only the configured provider pays the import cost.
_REGISTRY: dict[str, ProviderFactory] = {
    "anthropic": _anthropic_factory,
}


def build_provider(ai_settings: AISettings) -> LLMProvider:
    """Instantiate and return the provider configured in ``ai_settings.provider``.

    Args:
        ai_settings: The ``AISettings`` group from application settings.

    Returns:
        A ready-to-use ``LLMProvider`` instance.

    Raises:
        ValueError: If ``ai_settings.provider`` is not in the registry.  The error
            message lists the known providers so operators can fix the config quickly.
    """
    name = ai_settings.provider.lower()
    factory = _REGISTRY.get(name)
    if factory is None:
        known = ", ".join(sorted(_REGISTRY))
        raise ValueError(
            f"Unknown AI provider {name!r}. "
            f"Known providers: {known}. "
            f"Set AI__PROVIDER to one of: {known}."
        )
    return factory(ai_settings)


def registered_providers() -> list[str]:
    """Return the names of all registered providers (for diagnostics/docs)."""
    return sorted(_REGISTRY)
