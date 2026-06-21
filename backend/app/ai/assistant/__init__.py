"""Unified analytics assistant (#7/#11), built on the agent framework (#13)."""
from __future__ import annotations

from app.ai.assistant.service import (
    AssistantResult,
    AssistantService,
    get_assistant_service,
)

__all__ = ["AssistantResult", "AssistantService", "get_assistant_service"]
