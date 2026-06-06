"""Tenant-scoped Cube semantic-layer client (Phase 4, Task 4.1).

## Responsibilities

``SemanticLayerClient`` is the *only* backend component that talks to Cube.  It:

1. **Mints a per-request HS256 JWT** from ``CubeSettings.api_secret`` and the
   server-resolved ``TenantContext.clickhouse_db`` claim.  The secret never
   leaves this module; the token is never logged.
2. **POSTs a typed Cube JSON query** to ``{base_url}/cubejs-api/v1/load``.
3. **Parses and returns** the ``ResultSet`` rows as typed ``CubeRow`` dicts; numeric
   measure values are returned as ``Decimal`` so callers get exact arithmetic.

## Tenancy guarantee

The ``query()`` method signature forces the caller to supply a server-resolved
``TenantContext``.  The JWT's ``clickhouse_db`` claim is populated *exclusively*
from ``ctx.clickhouse_db`` — never from the request body or any other
caller-supplied parameter.  Two different ``TenantContext`` objects therefore
always produce JWTs with different ``clickhouse_db`` values; cross-tenant
leakage is structurally impossible through this path.

## Fail-closed behaviour

A 403 from Cube (JWT missing, expired, invalid signature, or absent
``clickhouse_db`` claim) is propagated immediately as a ``CubeAuthError``.
There is no retry, no fallback database, no silent degradation.

## Configuration

All connection parameters come from ``CubeSettings`` (injected at construction);
nothing infrastructure-specific is hardcoded here (golden rule 1).

## HTTP client

The constructor accepts any ``httpx.AsyncClient``-compatible object so tests
can substitute a fake transport without touching the process-wide singleton.
The FastAPI dependency ``get_semantic_layer_client`` wires the real client.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
import jwt
from fastapi import Depends

from app.core.config import CubeSettings, Settings, get_settings
from app.tenancy.context import TenantContext

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stable Cube identifiers (contract from docs/SEMANTIC_LAYER.md — DO NOT change
# without updating the Cube model and the docs page simultaneously).
# ---------------------------------------------------------------------------

#: The one cube exposed by the semantic layer.
CUBE_REGIONAL_SALES = "regional_sales"

#: Measure identifiers.
MEASURE_TOTAL_AMOUNT = f"{CUBE_REGIONAL_SALES}.total_amount"
MEASURE_AVG_SHARE = f"{CUBE_REGIONAL_SALES}.avg_share"

#: Dimension identifiers.
DIM_REGION = f"{CUBE_REGIONAL_SALES}.region"
DIM_SALES_RANK = f"{CUBE_REGIONAL_SALES}.sales_rank"

# How long (in seconds) a minted JWT lives before Cube rejects it.
_JWT_TTL_SECONDS = 3600

# Cube load endpoint path (always relative to base_url — never hardcoded host).
_LOAD_PATH = "/cubejs-api/v1/load"

# Cube meta endpoint path — returns governed cubes, measures, and dimensions.
_META_PATH = "/cubejs-api/v1/meta"

# ---------------------------------------------------------------------------
# Public result types
# ---------------------------------------------------------------------------

#: A single row returned by Cube, keyed by the fully-qualified measure/dimension
#: identifier (e.g. ``"regional_sales.region"``).  Numeric measures are cast to
#: ``Decimal``; all other values remain strings.
CubeRow = dict[str, str | Decimal]


class CubeAuthError(Exception):
    """Cube rejected the JWT (403).

    Raised instead of silently retrying so callers are forced to handle the
    failure.  The original HTTP status and Cube's error body are attached for
    structured logging; they must not be forwarded verbatim to the frontend.
    """

    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"Cube auth error: HTTP {status}")
        self.status = status
        self.body = body


class CubeQueryError(Exception):
    """Cube rejected the query as malformed (400) or returned an unexpected status."""

    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"Cube query error: HTTP {status}")
        self.status = status
        self.body = body


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class SemanticLayerClient:
    """Tenant-scoped HTTP client for the Cube semantic layer.

    Constructor accepts only infrastructure dependencies (settings + HTTP
    transport) so the class is trivially testable without live infra.  Tenant
    scope is supplied per call via a server-resolved ``TenantContext``.

    Args:
        cube_settings: ``CubeSettings`` group from the application settings.
        http_client: An ``httpx.AsyncClient`` (or test double) used for all
            outbound requests.  The caller is responsible for lifecycle
            management (open/close).
    """

    def __init__(
        self,
        cube_settings: CubeSettings,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._cfg = cube_settings
        self._http = http_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def meta(self, ctx: TenantContext) -> dict[str, Any]:
        """Return the governed semantic-layer schema for the current tenant.

        Calls ``GET {base_url}/cubejs-api/v1/meta`` with a per-tenant JWT so
        Cube scopes the response to ``ctx.clickhouse_db``.  The response is a
        dict with a ``cubes`` key listing every accessible cube together with
        its measures and dimensions.

        The LLM grounding stage uses this response exclusively — the LLM never
        learns about raw physical tables, only about the governed objects Cube
        exposes here.

        Args:
            ctx: Server-resolved tenant context (from ``get_tenant_context``).
                The JWT's ``clickhouse_db`` claim is populated only from here.

        Returns:
            The parsed JSON body as returned by Cube (dict with ``cubes`` list).

        Raises:
            CubeAuthError: If Cube returns 403 (bad/missing JWT).
            CubeQueryError: If Cube returns any other non-200 status.
        """
        token = self._mint_jwt(ctx)

        logger.info(
            "Cube meta tenant_id=%r clickhouse_db=%r",
            ctx.tenant_id,
            ctx.clickhouse_db,
        )

        url = self._cfg.base_url.rstrip("/") + _META_PATH
        response = await self._http.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
            },
        )

        if response.status_code == 403:
            logger.warning(
                "Cube /meta returned 403 for tenant_id=%r clickhouse_db=%r",
                ctx.tenant_id,
                ctx.clickhouse_db,
            )
            raise CubeAuthError(response.status_code, response.text)

        if response.status_code != 200:
            logger.error(
                "Cube /meta returned unexpected status %d for tenant_id=%r",
                response.status_code,
                ctx.tenant_id,
            )
            raise CubeQueryError(response.status_code, response.text)

        body: dict[str, Any] = response.json()
        cubes: list[Any] = body.get("cubes", [])
        logger.info(
            "Cube meta returned %d cube(s) for tenant_id=%r",
            len(cubes),
            ctx.tenant_id,
        )
        return body

    async def query(
        self,
        ctx: TenantContext,
        *,
        measures: list[str],
        dimensions: list[str],
        order: dict[str, str] | None = None,
        limit: int | None = None,
    ) -> list[CubeRow]:
        """Run a Cube query scoped to the given tenant and return typed rows.

        The ``clickhouse_db`` claim in the JWT is populated from
        ``ctx.clickhouse_db`` *only* — never from a caller-supplied parameter.

        Args:
            ctx: Server-resolved tenant context (from ``get_tenant_context``).
            measures: Fully-qualified Cube measure identifiers.
            dimensions: Fully-qualified Cube dimension identifiers.
            order: Optional ordering dict, e.g.
                ``{"regional_sales.total_amount": "desc"}``.
            limit: Optional row cap forwarded to Cube's ``limit``. The caller is
                responsible for clamping this to the platform maximum; this client
                only passes it through.

        Returns:
            A list of ``CubeRow`` dicts.  Numeric measure values are cast to
            ``Decimal``; dimension values remain strings.

        Raises:
            CubeAuthError: If Cube returns 403 (bad/missing JWT).
            CubeQueryError: If Cube returns 400 or any other non-200 status.
        """
        token = self._mint_jwt(ctx)
        body = self._build_body(
            measures=measures, dimensions=dimensions, order=order, limit=limit
        )

        # Log the query intent with tenant tagging; NEVER log the token or secret.
        logger.info(
            "Cube query tenant_id=%r clickhouse_db=%r measures=%r dimensions=%r",
            ctx.tenant_id,
            ctx.clickhouse_db,
            measures,
            dimensions,
        )

        url = self._cfg.base_url.rstrip("/") + _LOAD_PATH
        response = await self._http.post(
            url,
            json=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )

        if response.status_code == 403:
            # Log at WARNING — the tenant id is safe; do not log the token/body.
            logger.warning(
                "Cube returned 403 for tenant_id=%r clickhouse_db=%r — "
                "JWT invalid/expired or clickhouse_db claim absent",
                ctx.tenant_id,
                ctx.clickhouse_db,
            )
            raise CubeAuthError(response.status_code, response.text)

        if response.status_code != 200:
            logger.error(
                "Cube returned unexpected status %d for tenant_id=%r",
                response.status_code,
                ctx.tenant_id,
            )
            raise CubeQueryError(response.status_code, response.text)

        data: list[dict[str, Any]] = response.json().get("data", [])
        logger.info(
            "Cube query returned %d row(s) for tenant_id=%r",
            len(data),
            ctx.tenant_id,
        )
        return [self._cast_row(row, measures) for row in data]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _mint_jwt(self, ctx: TenantContext) -> str:
        """Mint a short-lived HS256 JWT carrying the tenant's ``clickhouse_db``.

        The ``clickhouse_db`` value is taken *only* from the server-resolved
        ``TenantContext`` — never from any caller-supplied argument.  The
        secret is accessed as a raw string exactly once here and is never
        stored in a local variable that might surface in tracebacks or logs.
        """
        now = datetime.now(tz=UTC)
        payload: dict[str, Any] = {
            "clickhouse_db": ctx.clickhouse_db,
            "exp": now + timedelta(seconds=_JWT_TTL_SECONDS),
        }
        # get_secret_value() is called inline; the result is not bound to a
        # named variable, so it cannot appear in a local-variable dump.
        return jwt.encode(
            payload,
            self._cfg.api_secret.get_secret_value(),
            algorithm="HS256",
        )

    @staticmethod
    def _build_body(
        *,
        measures: list[str],
        dimensions: list[str],
        order: dict[str, str] | None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Build the Cube JSON query body."""
        query: dict[str, Any] = {
            "measures": measures,
            "dimensions": dimensions,
        }
        if order:
            query["order"] = order
        if limit is not None:
            query["limit"] = limit
        return {"query": query}

    @staticmethod
    def _cast_row(raw: dict[str, Any], measures: list[str]) -> CubeRow:
        """Cast measure values from string to Decimal; leave dimensions as str.

        Cube's JSON serialiser returns numeric measures as strings (e.g.
        ``"142500.00"``).  We cast them to ``Decimal`` for exact arithmetic.
        Unrecognised or non-numeric values are passed through as strings so the
        caller receives the full row regardless.
        """
        row: CubeRow = {}
        measure_set = set(measures)
        for key, value in raw.items():
            if key in measure_set and value is not None:
                try:
                    row[key] = Decimal(str(value))
                except InvalidOperation:
                    row[key] = str(value)
            else:
                row[key] = str(value) if value is not None else ""
        return row


# ---------------------------------------------------------------------------
# Process-wide singleton HTTP client
# ---------------------------------------------------------------------------

_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    """Return the process-wide shared ``httpx.AsyncClient``.

    The client is created lazily on first call.  In tests, callers bypass this
    function entirely by constructing ``SemanticLayerClient`` directly with a
    fake transport.
    """
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient()
    return _http_client


async def close_http_client() -> None:
    """Close the process-wide shared client, if one was created.

    Wired into the FastAPI lifespan shutdown so the connection pool is released
    cleanly (no ``ResourceWarning: Unclosed client``). A no-op if the lazy client
    was never instantiated (e.g. a process that never issued a Cube query).
    """
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


def get_semantic_layer_client(
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> SemanticLayerClient:
    """FastAPI dependency: return a ``SemanticLayerClient`` wired from settings.

    Override in tests via ``app.dependency_overrides`` or construct directly.

    Example::

        @router.get("/metrics")
        async def get_metrics(
            ctx: TenantContext = Depends(get_tenant_context),
            sl: SemanticLayerClient = Depends(get_semantic_layer_client),
        ) -> list[CubeRow]:
            return await sl.query(
                ctx,
                measures=[MEASURE_TOTAL_AMOUNT],
                dimensions=[DIM_REGION],
                order={MEASURE_TOTAL_AMOUNT: "desc"},
            )
    """
    return SemanticLayerClient(
        cube_settings=settings.cube,
        http_client=_get_http_client(),
    )
