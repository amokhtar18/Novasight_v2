"""Standalone Model Context Protocol (MCP) server (#11/#12 tail).

This package runs as its own process (``python -m app.mcp.server``) and re-exposes
NovaSight's grounded, tenant-scoped chat tools — list/query semantic models and
validated NL→SQL — to *external* MCP clients (e.g. Claude Desktop), so the same
governed analytics primitives the in-process chat loop uses are available to any
MCP-capable assistant.

It is a **thin protocol adapter**, not a second analytics engine. Each tool call is
forwarded to the existing, already-audited backend HTTP API, carrying the caller's
``Authorization`` header verbatim. That keeps the security-critical invariants in
the single place that already enforces them:

* **Tenancy (golden rule 2).** The backend resolves the tenant from the verified
  JWT at its own boundary; the MCP process never parses, defaults, or trusts a
  tenant id. A missing/invalid token fails closed at the backend (401/403).
* **Grounding (golden rule 3).** The tools call only the governed semantic-layer
  and validated NL→SQL endpoints — there is no raw-table or arbitrary-SQL path.
* **Config (golden rule 1).** The backend URL, bind address, transport, and limits
  all come from ``settings.mcp`` — nothing is hardcoded.
"""
from __future__ import annotations

from app.mcp.backend_client import AnalyticsBackendClient, BackendError
from app.mcp.server import build_server

__all__ = ["AnalyticsBackendClient", "BackendError", "build_server"]
