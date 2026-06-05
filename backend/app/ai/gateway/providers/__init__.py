"""Concrete LLM provider implementations.

Each module here implements the ``LLMProvider`` protocol from
``app.ai.gateway.provider``.  The registry in ``app.ai.gateway.registry``
maps provider-name strings (from ``settings.ai.provider``) to factory
callables defined here.

Current providers
-----------------
- ``anthropic`` — Anthropic Claude via the official ``anthropic`` SDK.

Adding a new provider
---------------------
1. Create ``providers/<name>.py`` implementing ``LLMProvider``.
2. Register it in ``registry.py`` — no other file changes needed.
"""
