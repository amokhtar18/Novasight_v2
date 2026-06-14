"""Tests for the Cube semantic-layer client (Phase 4, Task 4.1).

## Strategy

A live Cube stack is not available in the test environment.  We substitute the
HTTP transport with a fake ``httpx.MockTransport`` / ``httpx.Response`` so every
test runs entirely in-process.  The ``SemanticLayerClient`` is constructed
directly (bypassing the FastAPI dependency) so we control both the settings and
the HTTP transport.

## Coverage

(a) JWT carries a valid HS256 signature signed with the configured secret, and
    the ``clickhouse_db`` claim equals ``TenantContext.clickhouse_db``.
(b) The Cube request body is well-formed with the stable identifiers (measures,
    dimensions, optional order).
(c) The parsed numeric result matches the faked Cube response; Decimal cast is
    verified.
(d) A 403 from Cube is propagated as ``CubeAuthError`` with no fallback/retry.
(e) A non-200/non-403 status is propagated as ``CubeQueryError``.
(f) TENANCY — two different TenantContexts produce JWTs with different
    ``clickhouse_db`` claims (no cross-tenant leak).
"""
from __future__ import annotations

import json
import time
import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import httpx
import jwt
import pytest

from app.ai.semantic.client import (
    _JWT_TTL_SECONDS,
    CUBE_REGIONAL_SALES,
    DIM_REGION,
    DIM_SALES_RANK,
    MEASURE_AVG_SHARE,
    MEASURE_TOTAL_AMOUNT,
    CubeAuthError,
    CubeQueryError,
    SemanticLayerClient,
)
from app.core.config import CubeSettings
from app.tenancy.context import TenantContext
from app.tenancy.resources import resources_for_slug

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SECRET = "test-secret-at-least-32-chars-long!"
_BASE_URL = "http://cube-test:4000"


def _cube_settings(secret: str = _SECRET, base_url: str = _BASE_URL) -> CubeSettings:
    """Build a ``CubeSettings`` instance with the given values."""
    from pydantic import SecretStr

    # CubeSettings is a BaseSettings subclass; supply values directly.
    settings = MagicMock(spec=CubeSettings)
    settings.base_url = base_url
    settings.api_secret = SecretStr(secret)
    return settings  # type: ignore[return-value]


def _make_ctx(slug: str) -> TenantContext:
    """Create a TenantContext from a slug using the real resource-naming logic."""
    res = resources_for_slug(slug)
    return TenantContext(
        tenant_id=str(uuid.uuid4()),
        iceberg_namespace=res.iceberg_namespace,
        clickhouse_db=res.clickhouse_db,
        dbt_schema=res.dbt_schema,
    )


def _cube_response(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a minimal Cube ResultSet response body."""
    return {"data": rows, "annotation": {}}


def _make_client(
    response_body: dict[str, Any] | None = None,
    status_code: int = 200,
    *,
    secret: str = _SECRET,
    base_url: str = _BASE_URL,
) -> tuple[SemanticLayerClient, list[httpx.Request]]:
    """Return a ``(client, captured_requests)`` pair backed by a fake transport.

    The fake transport returns a single ``httpx.Response`` with the given status
    and JSON body.  Every request is appended to ``captured_requests`` so tests
    can assert on URL, headers, and body.
    """
    captured: list[httpx.Request] = []

    body_bytes = json.dumps(response_body or {}).encode()

    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(status_code=status_code, content=body_bytes)

    transport = httpx.MockTransport(_handler)
    http_client = httpx.AsyncClient(transport=transport)
    settings = _cube_settings(secret=secret, base_url=base_url)
    client = SemanticLayerClient(cube_settings=settings, http_client=http_client)
    return client, captured


# ---------------------------------------------------------------------------
# (a) JWT is valid HS256, signed with the configured secret, correct claim
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jwt_is_hs256_signed_with_configured_secret() -> None:
    """The outgoing Authorization header carries a valid HS256 JWT."""
    ctx = _make_ctx("acme")
    cube_response = _cube_response([])
    client, captured = _make_client(response_body=cube_response)

    await client.query(ctx, measures=[MEASURE_TOTAL_AMOUNT], dimensions=[DIM_REGION])

    assert len(captured) == 1
    auth_header = captured[0].headers.get("authorization", "")
    assert auth_header.startswith("Bearer ")
    token = auth_header.split(" ", 1)[1]

    # Decode and verify the signature — must not raise.
    decoded = jwt.decode(token, _SECRET, algorithms=["HS256"])
    assert decoded["clickhouse_db"] == ctx.clickhouse_db


@pytest.mark.asyncio
async def test_jwt_clickhouse_db_matches_tenant_context() -> None:
    """The ``clickhouse_db`` JWT claim is exactly ``TenantContext.clickhouse_db``."""
    ctx = _make_ctx("widgetco")
    client, captured = _make_client(response_body=_cube_response([]))

    await client.query(ctx, measures=[MEASURE_TOTAL_AMOUNT], dimensions=[DIM_REGION])

    token = captured[0].headers["authorization"].split(" ", 1)[1]
    decoded = jwt.decode(token, _SECRET, algorithms=["HS256"])

    assert decoded["clickhouse_db"] == "tenant_widgetco"
    assert decoded["clickhouse_db"] == ctx.clickhouse_db


@pytest.mark.asyncio
async def test_jwt_exp_is_within_ttl_window() -> None:
    """The JWT must carry a short-lived ``exp`` ≈ now + the configured TTL.

    Asserts more than mere presence: the expiry must be in the future and within
    a tight band around ``_JWT_TTL_SECONDS``. This catches a clock-skew bug or an
    accidentally tiny/huge TTL that a presence-only check would pass.
    """
    ctx = _make_ctx("acme")
    client, captured = _make_client(response_body=_cube_response([]))

    before = time.time()
    await client.query(ctx, measures=[MEASURE_TOTAL_AMOUNT], dimensions=[DIM_REGION])

    token = captured[0].headers["authorization"].split(" ", 1)[1]
    decoded = jwt.decode(token, _SECRET, algorithms=["HS256"])

    assert "exp" in decoded
    remaining = decoded["exp"] - before
    # Within a few seconds of the configured TTL (and strictly in the future).
    assert _JWT_TTL_SECONDS - 5 <= remaining <= _JWT_TTL_SECONDS + 5


# ---------------------------------------------------------------------------
# (b) Cube request body is well-formed with the stable identifiers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_body_contains_measures_and_dimensions() -> None:
    """The POSTed body follows the Cube JSON query format with stable identifiers."""
    ctx = _make_ctx("acme")
    client, captured = _make_client(response_body=_cube_response([]))

    await client.query(
        ctx,
        measures=[MEASURE_TOTAL_AMOUNT, MEASURE_AVG_SHARE],
        dimensions=[DIM_REGION, DIM_SALES_RANK],
    )

    body = json.loads(captured[0].content)
    assert "query" in body
    query = body["query"]
    assert MEASURE_TOTAL_AMOUNT in query["measures"]
    assert MEASURE_AVG_SHARE in query["measures"]
    assert DIM_REGION in query["dimensions"]
    assert DIM_SALES_RANK in query["dimensions"]


@pytest.mark.asyncio
async def test_request_body_omits_order_when_none() -> None:
    """When ``order`` is None the key must be absent from the body."""
    ctx = _make_ctx("acme")
    client, captured = _make_client(response_body=_cube_response([]))

    await client.query(ctx, measures=[MEASURE_TOTAL_AMOUNT], dimensions=[DIM_REGION], order=None)

    body = json.loads(captured[0].content)
    assert "order" not in body["query"]


@pytest.mark.asyncio
async def test_request_body_includes_order_when_given() -> None:
    """When ``order`` is provided it must appear in the query body."""
    ctx = _make_ctx("acme")
    order = {MEASURE_TOTAL_AMOUNT: "desc"}
    client, captured = _make_client(response_body=_cube_response([]))

    await client.query(
        ctx,
        measures=[MEASURE_TOTAL_AMOUNT],
        dimensions=[DIM_REGION],
        order=order,
    )

    body = json.loads(captured[0].content)
    assert body["query"]["order"] == order


@pytest.mark.asyncio
async def test_request_body_omits_filters_when_none() -> None:
    """When ``filters`` is None the key must be absent from the body."""
    ctx = _make_ctx("acme")
    client, captured = _make_client(response_body=_cube_response([]))

    await client.query(ctx, measures=[MEASURE_TOTAL_AMOUNT], dimensions=[DIM_REGION], filters=None)

    body = json.loads(captured[0].content)
    assert "filters" not in body["query"]


@pytest.mark.asyncio
async def test_request_body_includes_filters_when_given() -> None:
    """When ``filters`` is provided it must appear verbatim in the query body."""
    ctx = _make_ctx("acme")
    filters = [{"member": DIM_REGION, "operator": "equals", "values": ["west"]}]
    client, captured = _make_client(response_body=_cube_response([]))

    await client.query(
        ctx,
        measures=[MEASURE_TOTAL_AMOUNT],
        dimensions=[DIM_REGION],
        filters=filters,
    )

    body = json.loads(captured[0].content)
    assert body["query"]["filters"] == filters


@pytest.mark.asyncio
async def test_request_targets_load_endpoint() -> None:
    """The request must POST to ``{base_url}/cubejs-api/v1/load``."""
    ctx = _make_ctx("acme")
    client, captured = _make_client(response_body=_cube_response([]))

    await client.query(ctx, measures=[MEASURE_TOTAL_AMOUNT], dimensions=[DIM_REGION])

    assert str(captured[0].url) == f"{_BASE_URL}/cubejs-api/v1/load"
    assert captured[0].method == "POST"


@pytest.mark.asyncio
async def test_request_content_type_is_json() -> None:
    """The Content-Type header must be ``application/json``."""
    ctx = _make_ctx("acme")
    client, captured = _make_client(response_body=_cube_response([]))

    await client.query(ctx, measures=[MEASURE_TOTAL_AMOUNT], dimensions=[DIM_REGION])

    assert "application/json" in captured[0].headers.get("content-type", "")


# ---------------------------------------------------------------------------
# (c) Parsed numeric result matches the faked Cube response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_numeric_measures_are_cast_to_decimal() -> None:
    """Measure values returned as strings by Cube are cast to ``Decimal``."""
    ctx = _make_ctx("acme")
    fake_rows = [
        {
            "regional_sales.region": "EMEA",
            "regional_sales.total_amount": "142500.00",
        },
        {
            "regional_sales.region": "APAC",
            "regional_sales.total_amount": "98300.00",
        },
    ]
    client, _ = _make_client(response_body=_cube_response(fake_rows))

    rows = await client.query(
        ctx,
        measures=[MEASURE_TOTAL_AMOUNT],
        dimensions=[DIM_REGION],
    )

    assert len(rows) == 2
    assert rows[0][MEASURE_TOTAL_AMOUNT] == Decimal("142500.00")
    assert rows[1][MEASURE_TOTAL_AMOUNT] == Decimal("98300.00")
    # Dimensions remain strings.
    assert rows[0][DIM_REGION] == "EMEA"
    assert rows[1][DIM_REGION] == "APAC"


@pytest.mark.asyncio
async def test_empty_data_array_returns_empty_list() -> None:
    """An empty ``data`` array in the Cube response maps to an empty list."""
    ctx = _make_ctx("acme")
    client, _ = _make_client(response_body=_cube_response([]))

    rows = await client.query(ctx, measures=[MEASURE_TOTAL_AMOUNT], dimensions=[DIM_REGION])

    assert rows == []


@pytest.mark.asyncio
async def test_non_numeric_measure_value_passes_through_as_string() -> None:
    """If Cube returns a non-numeric measure value it is kept as a string."""
    ctx = _make_ctx("acme")
    fake_rows = [{"regional_sales.total_amount": "N/A", "regional_sales.region": "LATAM"}]
    client, _ = _make_client(response_body=_cube_response(fake_rows))

    rows = await client.query(ctx, measures=[MEASURE_TOTAL_AMOUNT], dimensions=[DIM_REGION])

    assert rows[0][MEASURE_TOTAL_AMOUNT] == "N/A"


# ---------------------------------------------------------------------------
# (d) 403 from Cube → CubeAuthError, no fallback/retry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cube_403_raises_cube_auth_error() -> None:
    """A 403 from Cube must raise ``CubeAuthError`` immediately."""
    ctx = _make_ctx("acme")
    client, captured = _make_client(
        response_body={"error": "Not authorized"},
        status_code=403,
    )

    with pytest.raises(CubeAuthError) as exc_info:
        await client.query(ctx, measures=[MEASURE_TOTAL_AMOUNT], dimensions=[DIM_REGION])

    assert exc_info.value.status == 403
    # Only one request was made — no retry.
    assert len(captured) == 1


@pytest.mark.asyncio
async def test_cube_403_does_not_retry_with_different_db() -> None:
    """After a 403 the client must NOT retry against another database."""
    ctx = _make_ctx("acme")
    client, captured = _make_client(
        response_body={"error": "Not authorized"},
        status_code=403,
    )

    with pytest.raises(CubeAuthError):
        await client.query(ctx, measures=[MEASURE_TOTAL_AMOUNT], dimensions=[DIM_REGION])

    # Exactly one HTTP request — no retry.
    assert len(captured) == 1


# ---------------------------------------------------------------------------
# (e) Non-200/403 status → CubeQueryError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cube_400_raises_cube_query_error() -> None:
    """A 400 from Cube (malformed query) must raise ``CubeQueryError``."""
    ctx = _make_ctx("acme")
    client, _ = _make_client(
        response_body={"error": "Unknown measure: regional_sales.typo"},
        status_code=400,
    )

    with pytest.raises(CubeQueryError) as exc_info:
        await client.query(ctx, measures=["regional_sales.typo"], dimensions=[DIM_REGION])

    assert exc_info.value.status == 400


@pytest.mark.asyncio
async def test_cube_500_raises_cube_query_error() -> None:
    """A 500 from Cube must raise ``CubeQueryError``."""
    ctx = _make_ctx("acme")
    client, _ = _make_client(response_body={}, status_code=500)

    with pytest.raises(CubeQueryError) as exc_info:
        await client.query(ctx, measures=[MEASURE_TOTAL_AMOUNT], dimensions=[DIM_REGION])

    assert exc_info.value.status == 500


# ---------------------------------------------------------------------------
# (f) TENANCY — no cross-tenant leak between two TenantContexts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_different_tenants_produce_different_clickhouse_db_claims() -> None:
    """Two distinct TenantContexts must produce JWTs with different ``clickhouse_db`` claims."""
    ctx_a = _make_ctx("alpha")
    ctx_b = _make_ctx("betacorp")

    # Separate clients/transports so requests don't intermingle.
    client_a, captured_a = _make_client(response_body=_cube_response([]))
    client_b, captured_b = _make_client(response_body=_cube_response([]))

    await client_a.query(ctx_a, measures=[MEASURE_TOTAL_AMOUNT], dimensions=[DIM_REGION])
    await client_b.query(ctx_b, measures=[MEASURE_TOTAL_AMOUNT], dimensions=[DIM_REGION])

    token_a = captured_a[0].headers["authorization"].split(" ", 1)[1]
    token_b = captured_b[0].headers["authorization"].split(" ", 1)[1]

    decoded_a = jwt.decode(token_a, _SECRET, algorithms=["HS256"])
    decoded_b = jwt.decode(token_b, _SECRET, algorithms=["HS256"])

    # Claims are different — no cross-tenant bleed.
    assert decoded_a["clickhouse_db"] != decoded_b["clickhouse_db"]
    assert decoded_a["clickhouse_db"] == ctx_a.clickhouse_db
    assert decoded_b["clickhouse_db"] == ctx_b.clickhouse_db


@pytest.mark.asyncio
async def test_tenant_a_jwt_rejected_for_tenant_b_db() -> None:
    """A JWT minted for tenant A carries tenant A's db — it cannot access tenant B's data.

    We verify this by decoding both tokens and asserting they reference
    different databases.  The enforcement itself happens inside Cube's
    ``checkAuth`` (which rejects mismatches with 403); what we test here is
    that the client never mints a JWT with the wrong tenant's db.
    """
    ctx_a = _make_ctx("alpha")
    ctx_b = _make_ctx("betacorp")

    client_a, captured = _make_client(response_body=_cube_response([]))

    await client_a.query(ctx_a, measures=[MEASURE_TOTAL_AMOUNT], dimensions=[DIM_REGION])

    token_a = captured[0].headers["authorization"].split(" ", 1)[1]
    decoded_a = jwt.decode(token_a, _SECRET, algorithms=["HS256"])

    # The JWT minted for tenant A does NOT contain tenant B's database.
    assert decoded_a["clickhouse_db"] != ctx_b.clickhouse_db


# ---------------------------------------------------------------------------
# (g) Stable identifier constants are correct (contract regression)
# ---------------------------------------------------------------------------


def test_stable_identifiers_match_contract() -> None:
    """The exported constants must exactly match the identifiers in SEMANTIC_LAYER.md."""
    assert CUBE_REGIONAL_SALES == "regional_sales"
    assert MEASURE_TOTAL_AMOUNT == "regional_sales.total_amount"
    assert MEASURE_AVG_SHARE == "regional_sales.avg_share"
    assert DIM_REGION == "regional_sales.region"
    assert DIM_SALES_RANK == "regional_sales.sales_rank"


# ---------------------------------------------------------------------------
# (h) CubeSettings group is present on Settings (config integration)
# ---------------------------------------------------------------------------


def test_cube_settings_present_on_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """``Settings`` must expose a ``cube`` group with ``base_url`` and ``api_secret``."""
    from app.core.config import get_settings

    get_settings.cache_clear()

    # Minimal complete env (all required fields) — same pattern as test_settings.py.
    env: dict[str, str] = {
        "ENVIRONMENT": "test",
        "POSTGRES__HOST": "localhost",
        "POSTGRES__USER": "test",
        "POSTGRES__PASSWORD": "test",
        "POSTGRES__DB": "test",
        "REDIS__HOST": "localhost",
        "OBJECT_STORE__ENDPOINT_URL": "http://localhost:9000",
        "OBJECT_STORE__ACCESS_KEY": "testkey",
        "OBJECT_STORE__SECRET_KEY": "testsecret",
        "OBJECT_STORE__BUCKET": "test-bucket",
        "ICEBERG__CATALOG_URI": "http://localhost:8181",
        "ICEBERG__WAREHOUSE": "s3://test/warehouse",
        "CLICKHOUSE__HOST": "localhost",
        "CLICKHOUSE__PASSWORD": "test",
        "AI__PROVIDER": "openai",
        "AI__MODEL": "gpt-4o",
        "AI__API_KEY": "test-key",
        "AI__PROMPT_TEMPLATE_DIR": "prompts",
        "CUBE__BASE_URL": "http://cube:4000",
        "CUBE__API_SECRET": "a-random-secret-of-at-least-32-chars",
        "AUTH__DEV_STUB": "true",
        "AUTH__DEV_STUB_SECRET": "test-secret-at-least-32-chars-long!",
        "SEED_TENANT__SLUG": "local",
        "SEED_TENANT__NAME": "Local",
        "SEED_TENANT__ADMIN_EMAIL": "admin@local.test",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    settings = get_settings()

    assert settings.cube.base_url == "http://cube:4000"
    assert settings.cube.api_secret.get_secret_value() == "a-random-secret-of-at-least-32-chars"

    get_settings.cache_clear()


def test_cube_settings_fails_closed_without_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """``Settings`` must raise ValidationError when ``CUBE__BASE_URL`` is absent."""
    from pydantic import ValidationError

    from app.core.config import get_settings

    get_settings.cache_clear()

    env: dict[str, str] = {
        "ENVIRONMENT": "test",
        "POSTGRES__HOST": "localhost",
        "POSTGRES__USER": "test",
        "POSTGRES__PASSWORD": "test",
        "POSTGRES__DB": "test",
        "REDIS__HOST": "localhost",
        "OBJECT_STORE__ENDPOINT_URL": "http://localhost:9000",
        "OBJECT_STORE__ACCESS_KEY": "testkey",
        "OBJECT_STORE__SECRET_KEY": "testsecret",
        "OBJECT_STORE__BUCKET": "test-bucket",
        "ICEBERG__CATALOG_URI": "http://localhost:8181",
        "ICEBERG__WAREHOUSE": "s3://test/warehouse",
        "CLICKHOUSE__HOST": "localhost",
        "CLICKHOUSE__PASSWORD": "test",
        "AI__PROVIDER": "openai",
        "AI__MODEL": "gpt-4o",
        "AI__API_KEY": "test-key",
        "AI__PROMPT_TEMPLATE_DIR": "prompts",
        # CUBE__BASE_URL deliberately absent
        "CUBE__API_SECRET": "a-random-secret-of-at-least-32-chars",
        "AUTH__DEV_STUB": "true",
        "AUTH__DEV_STUB_SECRET": "test-secret-at-least-32-chars-long!",
        "SEED_TENANT__SLUG": "local",
        "SEED_TENANT__NAME": "Local",
        "SEED_TENANT__ADMIN_EMAIL": "admin@local.test",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("CUBE__BASE_URL", raising=False)

    with pytest.raises(ValidationError):
        get_settings()

    get_settings.cache_clear()


def test_cube_settings_fails_closed_without_api_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """``Settings`` must raise ValidationError when ``CUBE__API_SECRET`` is absent."""
    from pydantic import ValidationError

    from app.core.config import get_settings

    get_settings.cache_clear()

    env: dict[str, str] = {
        "ENVIRONMENT": "test",
        "POSTGRES__HOST": "localhost",
        "POSTGRES__USER": "test",
        "POSTGRES__PASSWORD": "test",
        "POSTGRES__DB": "test",
        "REDIS__HOST": "localhost",
        "OBJECT_STORE__ENDPOINT_URL": "http://localhost:9000",
        "OBJECT_STORE__ACCESS_KEY": "testkey",
        "OBJECT_STORE__SECRET_KEY": "testsecret",
        "OBJECT_STORE__BUCKET": "test-bucket",
        "ICEBERG__CATALOG_URI": "http://localhost:8181",
        "ICEBERG__WAREHOUSE": "s3://test/warehouse",
        "CLICKHOUSE__HOST": "localhost",
        "CLICKHOUSE__PASSWORD": "test",
        "AI__PROVIDER": "openai",
        "AI__MODEL": "gpt-4o",
        "AI__API_KEY": "test-key",
        "AI__PROMPT_TEMPLATE_DIR": "prompts",
        "CUBE__BASE_URL": "http://cube:4000",
        # CUBE__API_SECRET deliberately absent
        "AUTH__DEV_STUB": "true",
        "AUTH__DEV_STUB_SECRET": "test-secret-at-least-32-chars-long!",
        "SEED_TENANT__SLUG": "local",
        "SEED_TENANT__NAME": "Local",
        "SEED_TENANT__ADMIN_EMAIL": "admin@local.test",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("CUBE__API_SECRET", raising=False)

    with pytest.raises(ValidationError):
        get_settings()

    get_settings.cache_clear()
