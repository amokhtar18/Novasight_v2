"""Async HTTP client the MCP tools use to reach the NovaSight API.

Every method forwards the caller's ``Authorization`` header verbatim and maps the
backend's response onto a typed result or a safe :class:`BackendError`. The MCP
server is a transparent proxy: it holds no tenant logic and opens no SQL path of
its own — the backend remains the single auth/tenancy/grounding boundary (see the
package docstring).

Error policy (fail closed, never leak internals):

* 401 / 403  → the token is missing/invalid or not authorized for the tenant.
* 404        → surfaced with the backend's safe ``detail`` (e.g. unknown dataset).
* 422        → surfaced with the backend's safe validation ``detail``.
* 503        → backend / semantic layer / LLM provider temporarily unavailable.
* anything else, or a transport failure → a generic message; the detail is logged.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class BackendError(Exception):
    """A non-success response (or transport failure) from the backend API.

    ``message`` is SAFE to surface to the MCP client — it never carries provider
    keys, stack traces, or other internals. ``status`` is the originating HTTP
    status (``0`` for transport-level failures).
    """

    def __init__(self, message: str, *, status: int = 0) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _safe_detail(response: httpx.Response) -> str | None:
    """Return the backend's ``detail`` only when it is a plain string.

    Our endpoints raise ``HTTPException(..., detail="<safe message>")``, so a
    string detail is safe to relay. Pydantic request-validation errors instead
    produce a list of error objects; those are not relayed (a generic message is
    used) to avoid leaking field-level internals.
    """
    try:
        body = response.json()
    except ValueError:
        return None
    detail = body.get("detail") if isinstance(body, dict) else None
    return detail if isinstance(detail, str) else None


class AnalyticsBackendClient:
    """Thin async proxy to the governed analytics endpoints.

    One :class:`httpx.AsyncClient` is held for the process lifetime; close it via
    :meth:`aclose` on shutdown. ``base_url`` includes the API version prefix
    (e.g. ``http://api:8000/api/v1``) and comes from ``settings.mcp`` — never a
    literal (golden rule 1).
    """

    def __init__(self, base_url: str, *, timeout: float) -> None:
        # Re-join paths explicitly so the version prefix in base_url is preserved
        # (httpx would otherwise drop it for an absolute request path).
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        """Release the underlying HTTP connection pool (wire into shutdown)."""
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Tool-backing calls
    # ------------------------------------------------------------------

    async def list_semantic_models(self, authorization: str) -> list[dict[str, Any]]:
        """GET the governed semantic models the tenant may query."""
        data = await self._request("GET", "/semantic/models", authorization)
        return data if isinstance(data, list) else []

    async def query_semantic_model(
        self,
        authorization: str,
        *,
        measures: list[str],
        dimensions: list[str],
        limit: int | None,
    ) -> dict[str, Any]:
        """POST a structured measures/dimensions query to the semantic layer."""
        payload: dict[str, Any] = {"measures": measures, "dimensions": dimensions}
        if limit is not None:
            payload["limit"] = limit
        data = await self._request("POST", "/semantic/query", authorization, json=payload)
        return data if isinstance(data, dict) else {}

    async def nl_to_sql(self, authorization: str, *, question: str) -> dict[str, Any]:
        """POST an ad-hoc question to the validated NL→SQL endpoint."""
        data = await self._request(
            "POST", "/ai/query", authorization, json={"question": question}
        )
        return data if isinstance(data, dict) else {}

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        authorization: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> object:
        """Send one request with the forwarded auth header; map failures closed."""
        try:
            response = await self._client.request(
                method,
                f"{self._base_url}{path}",
                headers={"Authorization": authorization},
                json=json,
            )
        except httpx.HTTPError as exc:
            # Transport-level failure (DNS, connect, timeout). Log the type only.
            logger.warning(
                "MCP backend transport error: method=%s path=%s error=%s",
                method,
                path,
                type(exc).__name__,
            )
            raise BackendError(
                "The analytics backend is unreachable. Please try again."
            ) from exc
        return self._handle(response, path)

    @staticmethod
    def _handle(response: httpx.Response, path: str) -> object:
        """Return the JSON body on success, else raise a safe ``BackendError``."""
        if response.is_success:
            return response.json()

        status = response.status_code
        if status in (401, 403):
            raise BackendError(
                "Not authenticated or not authorized for this tenant. "
                "Provide a valid bearer token.",
                status=status,
            )
        if status == 404:
            raise BackendError(_safe_detail(response) or "Not found.", status=status)
        if status == 422:
            raise BackendError(
                _safe_detail(response) or "The request was rejected as invalid.",
                status=status,
            )
        if status == 503:
            raise BackendError(
                "The analytics backend is temporarily unavailable. Please try again.",
                status=status,
            )
        logger.warning("MCP backend unexpected status: path=%s status=%d", path, status)
        raise BackendError(
            "The analytics backend returned an unexpected error.", status=status
        )
