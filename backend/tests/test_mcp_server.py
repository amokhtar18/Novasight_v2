"""Tests for the standalone MCP server (#11/#12 tail).

Two layers, no live infra:

1. ``AnalyticsBackendClient`` — the proxy. Backed by an ``httpx.MockTransport`` so we
   assert the forwarded ``Authorization`` header, request path/body, and the
   fail-closed status→``BackendError`` mapping without a network.
2. ``build_server`` + the tool closures — fail-closed build, canonical tool names,
   and the end-to-end tool path (auth → proxy → row cap → ``ToolError``) driven via
   the registered tool ``fn`` with a fake request context.

The FastMCP transport plumbing (injecting the Starlette request into the tool
context) is SDK behaviour, verified against the SDK source; here we drive the tool
functions directly with a stand-in context.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.core.config import McpSettings
from app.mcp.backend_client import AnalyticsBackendClient, BackendError
from app.mcp.server import _authorization, _cap_rows, build_server

_AUTH = "Bearer test-token"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _client_with(handler: httpx.MockTransport) -> AnalyticsBackendClient:
    """A backend client whose HTTP calls are served by ``handler`` in-process."""
    client = AnalyticsBackendClient("http://testserver/api/v1", timeout=5.0)
    client._client = httpx.AsyncClient(transport=handler, base_url="http://testserver")
    return client


def _ctx(authorization: str | None) -> Any:
    """A stand-in for the FastMCP ``Context`` exposing only what the tools read."""
    headers: dict[str, str] = {}
    if authorization is not None:
        headers["authorization"] = authorization
    request = SimpleNamespace(headers=headers)
    return SimpleNamespace(request_context=SimpleNamespace(request=request))


def _tool_fn(server: Any, name: str) -> Any:
    """Return the raw (pre-wrap) handler registered for tool ``name``."""
    return server._tool_manager.get_tool(name).fn


# ---------------------------------------------------------------------------
# AnalyticsBackendClient — success paths + header/body forwarding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_models_forwards_auth_and_parses() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=[{"name": "regional_sales"}])

    client = _client_with(httpx.MockTransport(handler))
    try:
        models = await client.list_semantic_models(_AUTH)
    finally:
        await client.aclose()

    assert models == [{"name": "regional_sales"}]
    assert seen["path"] == "/api/v1/semantic/models"
    assert seen["auth"] == _AUTH  # token forwarded verbatim


@pytest.mark.asyncio
async def test_query_sends_measures_dimensions_limit() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"columns": ["a"], "rows": [[1]], "row_count": 1})

    client = _client_with(httpx.MockTransport(handler))
    try:
        result = await client.query_semantic_model(
            _AUTH, measures=["s.total"], dimensions=["s.region"], limit=10
        )
    finally:
        await client.aclose()

    assert result["row_count"] == 1
    assert seen["path"] == "/api/v1/semantic/query"
    assert seen["body"] == {"measures": ["s.total"], "dimensions": ["s.region"], "limit": 10}


@pytest.mark.asyncio
async def test_query_omits_limit_when_none() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"columns": [], "rows": [], "row_count": 0})

    client = _client_with(httpx.MockTransport(handler))
    try:
        await client.query_semantic_model(_AUTH, measures=["s.total"], dimensions=[], limit=None)
    finally:
        await client.aclose()

    assert "limit" not in seen["body"]  # None means "use the platform default"


@pytest.mark.asyncio
async def test_nl_to_sql_posts_question() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"sql": "SELECT 1", "columns": ["x"], "rows": [[1]], "row_count": 1}
        )

    client = _client_with(httpx.MockTransport(handler))
    try:
        result = await client.nl_to_sql(_AUTH, question="how many?")
    finally:
        await client.aclose()

    assert result["sql"] == "SELECT 1"
    assert seen["path"] == "/api/v1/ai/query"
    assert seen["body"] == {"question": "how many?"}


# ---------------------------------------------------------------------------
# AnalyticsBackendClient — fail-closed status mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.asyncio
async def test_unauthorized_maps_to_backend_error(status: int) -> None:
    client = _client_with(httpx.MockTransport(lambda r: httpx.Response(status)))
    try:
        with pytest.raises(BackendError) as exc:
            await client.list_semantic_models(_AUTH)
    finally:
        await client.aclose()
    assert exc.value.status == status
    assert "authoriz" in exc.value.message.lower() or "authenticat" in exc.value.message.lower()


@pytest.mark.asyncio
async def test_422_surfaces_safe_detail() -> None:
    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "Unknown measure(s): bogus"})

    client = _client_with(httpx.MockTransport(handler))
    try:
        with pytest.raises(BackendError) as exc:
            await client.query_semantic_model(_AUTH, measures=["bogus"], dimensions=[], limit=None)
    finally:
        await client.aclose()
    assert exc.value.message == "Unknown measure(s): bogus"
    assert exc.value.status == 422


@pytest.mark.asyncio
async def test_422_non_string_detail_uses_generic_message() -> None:
    # Pydantic request-validation errors return a list detail — never relayed.
    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": [{"loc": ["body"], "msg": "x"}]})

    client = _client_with(httpx.MockTransport(handler))
    try:
        with pytest.raises(BackendError) as exc:
            await client.nl_to_sql(_AUTH, question="x")
    finally:
        await client.aclose()
    assert exc.value.message == "The request was rejected as invalid."


@pytest.mark.asyncio
async def test_503_maps_to_unavailable() -> None:
    client = _client_with(httpx.MockTransport(lambda r: httpx.Response(503)))
    try:
        with pytest.raises(BackendError, match="temporarily unavailable"):
            await client.list_semantic_models(_AUTH)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_unexpected_status_is_generic() -> None:
    client = _client_with(httpx.MockTransport(lambda r: httpx.Response(500, text="stacktrace")))
    try:
        with pytest.raises(BackendError) as exc:
            await client.list_semantic_models(_AUTH)
    finally:
        await client.aclose()
    assert "stacktrace" not in exc.value.message  # internals never leaked
    assert exc.value.status == 500


@pytest.mark.asyncio
async def test_transport_error_maps_to_unreachable() -> None:
    def handler(_r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = _client_with(httpx.MockTransport(handler))
    try:
        with pytest.raises(BackendError, match="unreachable") as exc:
            await client.list_semantic_models(_AUTH)
    finally:
        await client.aclose()
    assert exc.value.status == 0
    assert "connection refused" not in exc.value.message


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_cap_rows_truncates_and_flags() -> None:
    result = {"columns": ["a"], "rows": [[1], [2], [3]], "row_count": 3}
    capped = _cap_rows(result, max_rows=2)
    assert capped["rows"] == [[1], [2]]
    assert capped["truncated"] is True
    assert capped["row_count"] == 3  # backend's full count preserved


def test_cap_rows_no_truncation() -> None:
    result = {"columns": ["a"], "rows": [[1]], "row_count": 1}
    capped = _cap_rows(result, max_rows=50)
    assert capped["rows"] == [[1]]
    assert capped["truncated"] is False


def test_authorization_returns_header() -> None:
    assert _authorization(_ctx(_AUTH)) == _AUTH


def test_authorization_missing_header_fails_closed() -> None:
    from mcp.server.fastmcp.exceptions import ToolError

    with pytest.raises(ToolError, match="bearer token"):
        _authorization(_ctx(None))


def test_authorization_no_request_fails_closed() -> None:
    from mcp.server.fastmcp.exceptions import ToolError

    ctx = SimpleNamespace(request_context=SimpleNamespace(request=None))
    with pytest.raises(ToolError, match="bearer token"):
        _authorization(ctx)


# ---------------------------------------------------------------------------
# build_server — fail-closed build + tool registration
# ---------------------------------------------------------------------------


def test_build_server_requires_backend_url() -> None:
    with pytest.raises(ValueError, match="MCP__BACKEND_BASE_URL"):
        build_server(McpSettings())


def test_build_server_registers_canonical_tools() -> None:
    client = _client_with(httpx.MockTransport(lambda r: httpx.Response(200, json=[])))
    server = build_server(McpSettings(), client=client)
    names = {t.name for t in server._tool_manager.list_tools()}
    assert names == {"list_semantic_models", "query_semantic_model", "nl_to_sql"}


# ---------------------------------------------------------------------------
# Tool closures — end-to-end (auth → proxy → row cap → ToolError)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_tool_forwards_token_and_caps_rows() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(
            200, json={"columns": ["a"], "rows": [[1], [2], [3]], "row_count": 3}
        )

    client = _client_with(httpx.MockTransport(handler))
    server = build_server(McpSettings(max_tool_rows=2), client=client)
    fn = _tool_fn(server, "query_semantic_model")

    result = await fn(_ctx(_AUTH), measures=["s.total"], dimensions=[], limit=None)

    assert seen["auth"] == _AUTH
    assert result["rows"] == [[1], [2]]
    assert result["truncated"] is True
    await client.aclose()


@pytest.mark.asyncio
async def test_query_tool_requires_a_field() -> None:
    from mcp.server.fastmcp.exceptions import ToolError

    client = _client_with(httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    server = build_server(McpSettings(), client=client)
    fn = _tool_fn(server, "query_semantic_model")

    with pytest.raises(ToolError, match="at least one measure or dimension"):
        await fn(_ctx(_AUTH), measures=[], dimensions=[], limit=None)
    await client.aclose()


@pytest.mark.asyncio
async def test_nl_to_sql_tool_missing_token_fails_closed() -> None:
    from mcp.server.fastmcp.exceptions import ToolError

    client = _client_with(httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    server = build_server(McpSettings(), client=client)
    fn = _tool_fn(server, "nl_to_sql")

    with pytest.raises(ToolError, match="bearer token"):
        await fn(_ctx(None), question="how many orders?")
    await client.aclose()


@pytest.mark.asyncio
async def test_backend_error_becomes_tool_error() -> None:
    from mcp.server.fastmcp.exceptions import ToolError

    client = _client_with(httpx.MockTransport(lambda r: httpx.Response(503)))
    server = build_server(McpSettings(), client=client)
    fn = _tool_fn(server, "list_semantic_models")

    with pytest.raises(ToolError, match="temporarily unavailable"):
        await fn(_ctx(_AUTH))
    await client.aclose()
