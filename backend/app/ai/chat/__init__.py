"""AI chat surface (#11/#12) — grounded, tenant-scoped tool-calling over the
governed semantic layer.

The chat service runs an LLM tool-dispatch loop: the model may call only a fixed
set of **grounded** tools that delegate to the existing, already-validated AI/
semantic services (no new SQL path; golden rule #3). Every tool runs under the
server-resolved ``TenantContext`` — the model can never widen the tenant scope.
"""
from __future__ import annotations

from app.ai.chat.service import (
    ChatResult,
    ChatService,
    get_chat_service,
)

__all__ = ["ChatResult", "ChatService", "get_chat_service"]
