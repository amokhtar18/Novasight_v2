"""Tests for Phase 4, Task 4.4 — NL→Chart grounded, validated endpoint.

Strategy
--------
All tests run entirely in-process.  Three external boundaries are mocked:
  1. The LLM gateway (``LLMGateway.complete``) — returns controlled JSON strings.
  2. The Cube semantic layer meta (``SemanticLayerClient.meta``) — returns a fake
     schema.
  3. The Cube semantic layer query (``SemanticLayerClient.query``) — returns fake
     rows.

No real network calls or live infra are required.

Acceptance criteria
-------------------
(a) A valid prompt produces a {spec, data} response: gateway returns a well-formed
    ChartSpec using governed metric_refs → validates → data resolved → response
    has the spec + matching columns/rows.
(b) An INVALID spec is rejected: gateway returns malformed JSON / unknown fields /
    missing required encoding / bad chart type → 422, data never resolved.
(c) An UNGROUNDED metric is rejected: gateway returns metric_refs=["not_a_metric"]
    or an x dimension not in meta → 422, query never executed.
(d) NO-CROSS-TENANT: meta()/query() are called with the server-resolved TenantContext
    only; tenant id cannot come from the request body.

On every rejection: ``SemanticLayerClient.query`` is NEVER called.
"""
from __future__ import annotations

import json
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ai.gateway.gateway import LLMGateway
from app.ai.gateway.loader import PromptLoader
from app.ai.gateway.provider import LLMResponse
from app.ai.nl_chart.grounding import build_chart_grounding_context
from app.ai.nl_chart.service import NLToChartService
from app.ai.nl_chart.validator import ChartValidationError, validate_chart_spec
from app.ai.semantic.client import CubeRow, SemanticLayerClient
from app.schemas.chart import ChartSpec
from app.tenancy.context import TenantContext
from app.tenancy.resources import resources_for_slug

# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------

_FAKE_META = {
    "cubes": [
        {
            "name": "regional_sales",
            "title": "Regional Sales",
            "description": "Sales data by region",
            "measures": [
                {
                    "name": "regional_sales.total_amount",
                    "title": "Total Amount",
                    "type": "sum",
                    "description": "Total sales amount",
                },
                {
                    "name": "regional_sales.avg_share",
                    "title": "Average Share",
                    "type": "avg",
                },
            ],
            "dimensions": [
                {
                    "name": "regional_sales.region",
                    "title": "Region",
                    "type": "string",
                },
                {
                    "name": "regional_sales.sales_rank",
                    "title": "Sales Rank",
                    "type": "number",
                },
            ],
        }
    ]
}

_ALLOWED_METRICS = {"regional_sales.total_amount", "regional_sales.avg_share"}
_ALLOWED_DIMS = {"regional_sales.region", "regional_sales.sales_rank"}

# A well-formed ChartSpec JSON the LLM might return.
_VALID_SPEC_DICT: dict[str, Any] = {
    "version": "1",
    "type": "bar",
    "query": {
        "metric_refs": ["regional_sales.total_amount"],
    },
    "encoding": {
        "x": "regional_sales.region",
        "series": [
            {"field": "regional_sales.total_amount", "name": "Total Amount"},
        ],
    },
    "options": {
        "title": "Sales by Region",
    },
}


def _make_ctx(slug: str = "acme") -> TenantContext:
    res = resources_for_slug(slug)
    return TenantContext(
        tenant_id=str(uuid.uuid4()),
        iceberg_namespace=res.iceberg_namespace,
        clickhouse_db=res.clickhouse_db,
        dbt_schema=res.dbt_schema,
    )


def _make_llm_response(text: str) -> LLMResponse:
    return LLMResponse(
        text=text,
        model="claude-test",
        usage={"input_tokens": 100, "output_tokens": 80},
    )


def _make_cube_rows(
    regions: list[str] | None = None,
    amounts: list[float] | None = None,
) -> list[CubeRow]:
    regions = regions or ["EMEA", "APAC"]
    amounts = amounts or [142500.0, 98300.0]
    return [
        {
            "regional_sales.region": r,
            "regional_sales.total_amount": Decimal(str(a)),
        }
        for r, a in zip(regions, amounts, strict=True)
    ]


def _make_service(
    *,
    gateway_response: LLMResponse | None = None,
    meta_response: dict[str, Any] | None = None,
    cube_rows: list[CubeRow] | None = None,
) -> tuple[NLToChartService, MagicMock, MagicMock, MagicMock]:
    """Build an NLToChartService with all external deps mocked.

    Returns (service, mock_gateway, mock_meta, mock_query).
    The mock_meta and mock_query are both on the same SemanticLayerClient mock.
    We return them separately for assertion convenience.
    """
    prompts_dir = Path(__file__).parent.parent / "app" / "ai" / "prompts"
    loader = PromptLoader(str(prompts_dir))

    mock_gateway = MagicMock(spec=LLMGateway)
    effective_response = gateway_response or _make_llm_response(
        json.dumps(_VALID_SPEC_DICT)
    )
    mock_gateway.complete = AsyncMock(return_value=effective_response)

    mock_semantic = MagicMock(spec=SemanticLayerClient)
    mock_semantic.meta = AsyncMock(return_value=meta_response or _FAKE_META)
    mock_semantic.query = AsyncMock(return_value=cube_rows or _make_cube_rows())

    svc = NLToChartService(
        gateway=mock_gateway,  # type: ignore[arg-type]
        prompt_loader=loader,
        semantic_client=mock_semantic,  # type: ignore[arg-type]
    )
    return svc, mock_gateway, mock_semantic.meta, mock_semantic.query


# ===========================================================================
# (a) Valid prompt → spec + data
# ===========================================================================


@pytest.mark.asyncio
async def test_valid_request_returns_spec_and_data() -> None:
    """A valid NL request produces a spec with metric_refs and aligned data columns."""
    ctx = _make_ctx()
    cube_rows = _make_cube_rows(
        regions=["EMEA", "APAC", "AMER"],
        amounts=[142500.0, 98300.0, 201000.0],
    )
    svc, _, mock_meta, mock_query = _make_service(cube_rows=cube_rows)

    spec, data = await svc.generate(ctx, request="Show total sales by region as a bar chart")

    # Spec shape
    assert spec.type == "bar"
    assert spec.query.metric_refs == ["regional_sales.total_amount"]
    assert spec.encoding.x == "regional_sales.region"
    assert len(spec.encoding.series) == 1
    assert spec.encoding.series[0].field == "regional_sales.total_amount"

    # Data columns aligned to encoding
    assert data.columns[0] == "regional_sales.region"
    assert data.columns[1] == "regional_sales.total_amount"
    assert data.row_count == 3
    assert len(data.rows) == 3

    # meta called with correct tenant
    mock_meta.assert_called_once_with(ctx)
    # query called with correct tenant and measures/dimensions
    mock_query.assert_called_once_with(
        ctx,
        measures=["regional_sales.total_amount"],
        dimensions=["regional_sales.region"],
    )


@pytest.mark.asyncio
async def test_spec_version_is_preserved() -> None:
    """The chart spec version from the LLM output is preserved in the response."""
    ctx = _make_ctx()
    svc, _, _, _ = _make_service()

    spec, _ = await svc.generate(ctx, request="Bar chart of sales by region")
    assert spec.version == "1"


@pytest.mark.asyncio
async def test_decimal_values_cast_to_float() -> None:
    """Decimal measure values from Cube are cast to float in the QueryResponse rows."""
    ctx = _make_ctx()
    cube_rows: list[CubeRow] = [
        {
            "regional_sales.region": "EMEA",
            "regional_sales.total_amount": Decimal("142500.50"),
        }
    ]
    svc, _, _, _ = _make_service(cube_rows=cube_rows)

    _, data = await svc.generate(ctx, request="Show sales by region")

    assert data.rows[0][1] == pytest.approx(142500.50)
    assert isinstance(data.rows[0][1], float)


@pytest.mark.asyncio
async def test_line_chart_type_is_accepted() -> None:
    """A line chart spec is accepted and passes through correctly."""
    ctx = _make_ctx()
    spec_dict = {
        **_VALID_SPEC_DICT,
        "type": "line",
        "options": {"title": "Trend"},
    }
    svc, _, _, _ = _make_service(gateway_response=_make_llm_response(json.dumps(spec_dict)))

    spec, _ = await svc.generate(ctx, request="Line chart of sales trend")
    assert spec.type == "line"


@pytest.mark.asyncio
async def test_table_chart_with_no_x_is_accepted() -> None:
    """A table chart spec with no encoding.x is valid and resolved."""
    ctx = _make_ctx()
    table_spec: dict[str, Any] = {
        "version": "1",
        "type": "table",
        "query": {"metric_refs": ["regional_sales.total_amount"]},
        "encoding": {
            "series": [{"field": "regional_sales.total_amount", "name": "Total Amount"}],
        },
        "options": {"title": None},
    }
    svc, _, _, mock_query = _make_service(
        gateway_response=_make_llm_response(json.dumps(table_spec)),
    )

    spec, data = await svc.generate(ctx, request="Show a data table of total amounts")

    assert spec.type == "table"
    assert spec.encoding.x is None
    # columns: no x, just the series field
    assert data.columns == ["regional_sales.total_amount"]
    # query called with empty dimensions
    mock_query.assert_called_once_with(
        ctx,
        measures=["regional_sales.total_amount"],
        dimensions=[],
    )


@pytest.mark.asyncio
async def test_multiple_metrics_in_spec() -> None:
    """A spec with two metric_refs and two series is valid and resolved."""
    ctx = _make_ctx()
    multi_spec: dict[str, Any] = {
        "version": "1",
        "type": "bar",
        "query": {
            "metric_refs": [
                "regional_sales.total_amount",
                "regional_sales.avg_share",
            ],
        },
        "encoding": {
            "x": "regional_sales.region",
            "series": [
                {"field": "regional_sales.total_amount", "name": "Total Amount"},
                {"field": "regional_sales.avg_share", "name": "Avg Share"},
            ],
        },
        "options": {"title": "Sales overview"},
    }
    cube_rows: list[CubeRow] = [
        {
            "regional_sales.region": "EMEA",
            "regional_sales.total_amount": Decimal("100"),
            "regional_sales.avg_share": Decimal("0.35"),
        }
    ]
    svc, _, _, mock_query = _make_service(
        gateway_response=_make_llm_response(json.dumps(multi_spec)),
        cube_rows=cube_rows,
    )

    spec, data = await svc.generate(ctx, request="Show both metrics by region")

    assert len(spec.query.metric_refs) == 2
    assert len(spec.encoding.series) == 2
    assert data.columns == [
        "regional_sales.region",
        "regional_sales.total_amount",
        "regional_sales.avg_share",
    ]
    mock_query.assert_called_once_with(
        ctx,
        measures=["regional_sales.total_amount", "regional_sales.avg_share"],
        dimensions=["regional_sales.region"],
    )


# ===========================================================================
# (b) Invalid spec is rejected; query NEVER called
# ===========================================================================


@pytest.mark.asyncio
async def test_malformed_json_is_rejected() -> None:
    """Malformed JSON from the LLM is rejected; query is never called."""
    ctx = _make_ctx()
    svc, _, _, mock_query = _make_service(
        gateway_response=_make_llm_response("not valid json {{{")
    )

    with pytest.raises(ChartValidationError) as exc_info:
        await svc.generate(ctx, request="Show sales")

    reason = exc_info.value.reason.lower()
    assert "not valid json" in reason or "json" in reason
    mock_query.assert_not_called()


@pytest.mark.asyncio
async def test_unknown_extra_field_is_rejected() -> None:
    """A JSON object with extra fields not in ChartSpec is rejected."""
    ctx = _make_ctx()
    spec_with_extra = {**_VALID_SPEC_DICT, "evil_field": "injected"}
    svc, _, _, mock_query = _make_service(
        gateway_response=_make_llm_response(json.dumps(spec_with_extra))
    )

    with pytest.raises(ChartValidationError) as exc_info:
        await svc.generate(ctx, request="Show sales")

    reason = exc_info.value.reason.lower()
    assert "schema" in reason or "extra" in reason or "forbidden" in reason
    mock_query.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_chart_type_is_rejected() -> None:
    """An unsupported chart type (e.g. 'sankey') is rejected."""
    ctx = _make_ctx()
    bad_spec = {**_VALID_SPEC_DICT, "type": "sankey"}
    svc, _, _, mock_query = _make_service(
        gateway_response=_make_llm_response(json.dumps(bad_spec))
    )

    with pytest.raises(ChartValidationError):
        await svc.generate(ctx, request="Show sales sankey")

    mock_query.assert_not_called()


@pytest.mark.asyncio
async def test_missing_series_is_rejected() -> None:
    """A spec with empty series is rejected (at least one series required)."""
    ctx = _make_ctx()
    bad_spec: dict[str, Any] = {
        "version": "1",
        "type": "bar",
        "query": {"metric_refs": ["regional_sales.total_amount"]},
        "encoding": {"x": "regional_sales.region", "series": []},
        "options": {"title": None},
    }
    svc, _, _, mock_query = _make_service(
        gateway_response=_make_llm_response(json.dumps(bad_spec))
    )

    with pytest.raises(ChartValidationError):
        await svc.generate(ctx, request="Show sales")

    mock_query.assert_not_called()


@pytest.mark.asyncio
async def test_missing_x_for_axis_chart_is_rejected() -> None:
    """A bar chart spec without encoding.x is rejected."""
    ctx = _make_ctx()
    bad_spec: dict[str, Any] = {
        "version": "1",
        "type": "bar",
        "query": {"metric_refs": ["regional_sales.total_amount"]},
        "encoding": {
            "series": [{"field": "regional_sales.total_amount"}],
        },
        "options": {"title": None},
    }
    svc, _, _, mock_query = _make_service(
        gateway_response=_make_llm_response(json.dumps(bad_spec))
    )

    with pytest.raises(ChartValidationError):
        await svc.generate(ctx, request="Show sales")

    mock_query.assert_not_called()


@pytest.mark.asyncio
async def test_inline_query_is_rejected() -> None:
    """A spec with an inline dataset query (not metric_refs) is rejected on the AI path."""
    ctx = _make_ctx()
    inline_spec: dict[str, Any] = {
        "version": "1",
        "type": "bar",
        "query": {
            "dataset_id": str(uuid.uuid4()),
            "query": {
                "dimensions": ["region"],
                "metrics": [{"function": "sum", "column": "amount", "alias": "total"}],
            },
            "metric_refs": [],
        },
        "encoding": {
            "x": "regional_sales.region",
            "series": [{"field": "regional_sales.total_amount"}],
        },
        "options": {"title": None},
    }
    svc, _, _, mock_query = _make_service(
        gateway_response=_make_llm_response(json.dumps(inline_spec))
    )

    with pytest.raises(ChartValidationError) as exc_info:
        await svc.generate(ctx, request="Show sales inline")

    reason = exc_info.value.reason.lower()
    assert "metric_refs" in reason or "inline" in reason or "query" in reason
    mock_query.assert_not_called()


@pytest.mark.asyncio
async def test_unsatisfiable_sentinel_is_rejected() -> None:
    """UNSATISFIABLE from the LLM is rejected with a user-friendly message."""
    ctx = _make_ctx()
    svc, _, _, mock_query = _make_service(
        gateway_response=_make_llm_response("UNSATISFIABLE")
    )

    with pytest.raises(ChartValidationError) as exc_info:
        await svc.generate(ctx, request="Show the weather forecast")

    reason = exc_info.value.reason.lower()
    assert "cannot be answered" in reason or "rephrase" in reason or "manual" in reason
    mock_query.assert_not_called()


@pytest.mark.asyncio
async def test_json_non_object_is_rejected() -> None:
    """A JSON array (not an object) is rejected."""
    ctx = _make_ctx()
    svc, _, _, mock_query = _make_service(
        gateway_response=_make_llm_response('["not", "an", "object"]')
    )

    with pytest.raises(ChartValidationError):
        await svc.generate(ctx, request="Show something")

    mock_query.assert_not_called()


# ===========================================================================
# (c) Ungrounded metric/dimension is rejected; query NEVER called
# ===========================================================================


@pytest.mark.asyncio
async def test_ungrounded_metric_ref_is_rejected() -> None:
    """A metric_refs entry not in the Cube meta is rejected."""
    ctx = _make_ctx()
    bad_spec: dict[str, Any] = {
        "version": "1",
        "type": "bar",
        "query": {"metric_refs": ["regional_sales.not_a_metric"]},
        "encoding": {
            "x": "regional_sales.region",
            "series": [{"field": "regional_sales.not_a_metric"}],
        },
        "options": {"title": None},
    }
    svc, _, _, mock_query = _make_service(
        gateway_response=_make_llm_response(json.dumps(bad_spec))
    )

    with pytest.raises(ChartValidationError) as exc_info:
        await svc.generate(ctx, request="Show fake metric")

    reason = exc_info.value.reason.lower()
    assert "not_a_metric" in reason or "governed" in reason or "semantic" in reason
    mock_query.assert_not_called()


@pytest.mark.asyncio
async def test_ungrounded_series_field_is_rejected() -> None:
    """An encoding.series[].field not in the Cube meta is rejected."""
    ctx = _make_ctx()
    bad_spec: dict[str, Any] = {
        "version": "1",
        "type": "bar",
        "query": {"metric_refs": ["regional_sales.total_amount"]},
        "encoding": {
            "x": "regional_sales.region",
            "series": [{"field": "regional_sales.invented_field"}],
        },
        "options": {"title": None},
    }
    svc, _, _, mock_query = _make_service(
        gateway_response=_make_llm_response(json.dumps(bad_spec))
    )

    with pytest.raises(ChartValidationError) as exc_info:
        await svc.generate(ctx, request="Show invented field")

    reason = exc_info.value.reason.lower()
    assert "invented_field" in reason or "governed" in reason or "semantic" in reason
    mock_query.assert_not_called()


@pytest.mark.asyncio
async def test_ungrounded_dimension_x_is_rejected() -> None:
    """An encoding.x value not in the Cube meta is rejected."""
    ctx = _make_ctx()
    bad_spec: dict[str, Any] = {
        "version": "1",
        "type": "bar",
        "query": {"metric_refs": ["regional_sales.total_amount"]},
        "encoding": {
            "x": "regional_sales.not_a_dimension",
            "series": [{"field": "regional_sales.total_amount"}],
        },
        "options": {"title": None},
    }
    svc, _, _, mock_query = _make_service(
        gateway_response=_make_llm_response(json.dumps(bad_spec))
    )

    with pytest.raises(ChartValidationError) as exc_info:
        await svc.generate(ctx, request="Show sales by unknown dim")

    reason = exc_info.value.reason.lower()
    assert "not_a_dimension" in reason or "governed" in reason or "dimension" in reason
    mock_query.assert_not_called()


@pytest.mark.asyncio
async def test_empty_meta_rejects_any_spec() -> None:
    """When Cube returns no cubes, no metric or dimension is governed — all specs fail."""
    ctx = _make_ctx()
    svc, _, _, mock_query = _make_service(
        meta_response={"cubes": []},
    )

    with pytest.raises(ChartValidationError):
        await svc.generate(ctx, request="Show sales by region")

    mock_query.assert_not_called()


# ===========================================================================
# (d) NO-CROSS-TENANT: tenant context comes from server, not request body
# ===========================================================================


@pytest.mark.asyncio
async def test_meta_called_with_server_resolved_tenant_context() -> None:
    """meta() is always called with the server-resolved TenantContext (not from body)."""
    ctx = _make_ctx("acme")
    svc, _, mock_meta, _ = _make_service()

    await svc.generate(ctx, request="Show sales by region")

    mock_meta.assert_called_once_with(ctx)
    # The ctx passed to meta must be the one the server resolved.
    actual_ctx = mock_meta.call_args[0][0]
    assert actual_ctx.tenant_id == ctx.tenant_id
    assert actual_ctx.clickhouse_db == ctx.clickhouse_db


@pytest.mark.asyncio
async def test_query_called_with_server_resolved_tenant_context() -> None:
    """query() is always called with the server-resolved TenantContext."""
    ctx = _make_ctx("widgetco")
    svc, _, _, mock_query = _make_service()

    await svc.generate(ctx, request="Show sales by region")

    mock_query.assert_called_once()
    actual_ctx = mock_query.call_args[0][0]
    assert actual_ctx.tenant_id == ctx.tenant_id
    assert actual_ctx.clickhouse_db == ctx.clickhouse_db


@pytest.mark.asyncio
async def test_two_tenants_have_independent_meta_calls() -> None:
    """meta() is called separately for each tenant with the correct context."""
    ctx_a = _make_ctx("alpha")
    ctx_b = _make_ctx("betacorp")

    calls: list[TenantContext] = []

    async def _meta_side_effect(ctx: TenantContext) -> dict[str, Any]:
        calls.append(ctx)
        return _FAKE_META

    async def _query_side_effect(ctx: TenantContext, **_kwargs: Any) -> list[CubeRow]:
        return _make_cube_rows()

    prompts_dir = Path(__file__).parent.parent / "app" / "ai" / "prompts"
    loader = PromptLoader(str(prompts_dir))

    mock_gateway = MagicMock(spec=LLMGateway)
    mock_gateway.complete = AsyncMock(
        return_value=_make_llm_response(json.dumps(_VALID_SPEC_DICT))
    )
    mock_semantic = MagicMock(spec=SemanticLayerClient)
    mock_semantic.meta = AsyncMock(side_effect=_meta_side_effect)
    mock_semantic.query = AsyncMock(side_effect=_query_side_effect)

    svc = NLToChartService(
        gateway=mock_gateway,  # type: ignore[arg-type]
        prompt_loader=loader,
        semantic_client=mock_semantic,  # type: ignore[arg-type]
    )

    await svc.generate(ctx_a, request="Show sales by region")
    await svc.generate(ctx_b, request="Show sales by region")

    assert len(calls) == 2
    assert calls[0].tenant_id == ctx_a.tenant_id
    assert calls[1].tenant_id == ctx_b.tenant_id
    assert calls[0].clickhouse_db != calls[1].clickhouse_db


# ===========================================================================
# Direct validator unit tests
# ===========================================================================


def test_direct_validator_accepts_valid_spec() -> None:
    """validate_chart_spec passes a well-formed spec with governed refs."""
    result = validate_chart_spec(
        json.dumps(_VALID_SPEC_DICT),
        allowed_metrics=_ALLOWED_METRICS,
        allowed_dimensions=_ALLOWED_DIMS,
    )
    assert isinstance(result, ChartSpec)
    assert result.type == "bar"


def test_direct_validator_rejects_unsatisfiable() -> None:
    """validate_chart_spec rejects the UNSATISFIABLE sentinel."""
    with pytest.raises(ChartValidationError) as exc_info:
        validate_chart_spec(
            "UNSATISFIABLE",
            allowed_metrics=_ALLOWED_METRICS,
            allowed_dimensions=_ALLOWED_DIMS,
        )
    reason = exc_info.value.reason.lower()
    assert "cannot be answered" in reason or "rephrase" in reason or "manual" in reason


def test_direct_validator_rejects_malformed_json() -> None:
    """validate_chart_spec rejects non-JSON output."""
    with pytest.raises(ChartValidationError) as exc_info:
        validate_chart_spec(
            "SELECT * FROM sales",
            allowed_metrics=_ALLOWED_METRICS,
            allowed_dimensions=_ALLOWED_DIMS,
        )
    assert "json" in exc_info.value.reason.lower()


def test_direct_validator_accepts_markdown_fenced_json() -> None:
    """A spec wrapped in a ```json … ``` fence is recovered and accepted.

    Models routinely wrap output in markdown fences even when told not to; the
    validator must tolerate this without weakening any downstream guardrail.
    """
    fenced = "```json\n" + json.dumps(_VALID_SPEC_DICT) + "\n```"
    result = validate_chart_spec(
        fenced,
        allowed_metrics=_ALLOWED_METRICS,
        allowed_dimensions=_ALLOWED_DIMS,
    )
    assert isinstance(result, ChartSpec)
    assert result.type == "bar"


def test_direct_validator_accepts_bare_fenced_json() -> None:
    """A spec wrapped in a bare ``` … ``` fence (no language tag) is accepted."""
    fenced = "```\n" + json.dumps(_VALID_SPEC_DICT) + "\n```"
    result = validate_chart_spec(
        fenced,
        allowed_metrics=_ALLOWED_METRICS,
        allowed_dimensions=_ALLOWED_DIMS,
    )
    assert isinstance(result, ChartSpec)


def test_direct_validator_accepts_json_with_preamble() -> None:
    """Surrounding prose is stripped; the embedded JSON object is recovered."""
    noisy = "Here is your chart spec:\n" + json.dumps(_VALID_SPEC_DICT) + "\nHope that helps!"
    result = validate_chart_spec(
        noisy,
        allowed_metrics=_ALLOWED_METRICS,
        allowed_dimensions=_ALLOWED_DIMS,
    )
    assert isinstance(result, ChartSpec)


def test_direct_validator_rejects_empty_output() -> None:
    """An empty LLM response is rejected with a clear, user-safe message."""
    with pytest.raises(ChartValidationError) as exc_info:
        validate_chart_spec(
            "   ",
            allowed_metrics=_ALLOWED_METRICS,
            allowed_dimensions=_ALLOWED_DIMS,
        )
    assert "empty" in exc_info.value.reason.lower()


def test_direct_validator_rejects_extra_fields() -> None:
    """Extra JSON fields are rejected (no mutation of the shared ChartSpec contract)."""
    spec_with_extra = {**_VALID_SPEC_DICT, "injected": "payload"}
    with pytest.raises(ChartValidationError) as exc_info:
        validate_chart_spec(
            json.dumps(spec_with_extra),
            allowed_metrics=_ALLOWED_METRICS,
            allowed_dimensions=_ALLOWED_DIMS,
        )
    reason = exc_info.value.reason.lower()
    assert "schema" in reason or "extra" in reason or "forbidden" in reason


def test_direct_validator_rejects_ungrounded_metric() -> None:
    """An ungrounded metric_ref raises ChartValidationError."""
    bad_spec = {
        **_VALID_SPEC_DICT,
        "query": {"metric_refs": ["regional_sales.invented"]},
        "encoding": {
            "x": "regional_sales.region",
            "series": [{"field": "regional_sales.invented"}],
        },
    }
    with pytest.raises(ChartValidationError) as exc_info:
        validate_chart_spec(
            json.dumps(bad_spec),
            allowed_metrics=_ALLOWED_METRICS,
            allowed_dimensions=_ALLOWED_DIMS,
        )
    reason = exc_info.value.reason.lower()
    assert "invented" in reason or "governed" in reason


def test_direct_validator_rejects_ungrounded_dimension() -> None:
    """An ungrounded encoding.x raises ChartValidationError."""
    bad_spec = {
        **_VALID_SPEC_DICT,
        "encoding": {
            "x": "regional_sales.not_a_dim",
            "series": [{"field": "regional_sales.total_amount"}],
        },
    }
    with pytest.raises(ChartValidationError) as exc_info:
        validate_chart_spec(
            json.dumps(bad_spec),
            allowed_metrics=_ALLOWED_METRICS,
            allowed_dimensions=_ALLOWED_DIMS,
        )
    reason = exc_info.value.reason.lower()
    assert "not_a_dim" in reason or "dimension" in reason


def test_direct_validator_rejects_dataset_id_with_metric_refs() -> None:
    """A spec smuggling a dataset_id alongside valid metric_refs is rejected (C1).

    Even though _resolve only queries metric_refs, an LLM-emitted dataset_id would
    otherwise survive into the returned spec, pointing at a (possibly other-tenant)
    dataset record. The AI path is metric_refs ONLY.
    """
    bad_spec = {
        **_VALID_SPEC_DICT,
        "query": {
            "dataset_id": "00000000-0000-0000-0000-000000000001",
            "metric_refs": ["regional_sales.total_amount"],
        },
    }
    with pytest.raises(ChartValidationError) as exc_info:
        validate_chart_spec(
            json.dumps(bad_spec),
            allowed_metrics=_ALLOWED_METRICS,
            allowed_dimensions=_ALLOWED_DIMS,
        )
    assert "dataset_id" in exc_info.value.reason.lower()


def test_direct_validator_rejects_series_field_not_in_metric_refs() -> None:
    """A grounded series field absent from metric_refs is rejected (C2).

    Both fields are governed metrics, but the series field is not listed in
    metric_refs, so Cube would never return data for it — the renderer would
    silently plot nulls. Must be rejected.
    """
    bad_spec = {
        **_VALID_SPEC_DICT,
        "query": {"metric_refs": ["regional_sales.total_amount"]},
        "encoding": {
            "x": "regional_sales.region",
            "series": [{"field": "regional_sales.avg_share"}],
        },
    }
    with pytest.raises(ChartValidationError) as exc_info:
        validate_chart_spec(
            json.dumps(bad_spec),
            allowed_metrics=_ALLOWED_METRICS,
            allowed_dimensions=_ALLOWED_DIMS,
        )
    assert "metric_refs" in exc_info.value.reason.lower()


def test_direct_validator_rejects_dimension_in_metric_refs() -> None:
    """A governed dimension smuggled into metric_refs (metric position) is rejected (M4)."""
    bad_spec = {
        **_VALID_SPEC_DICT,
        "query": {"metric_refs": ["regional_sales.region"]},
        "encoding": {
            "x": "regional_sales.region",
            "series": [{"field": "regional_sales.region"}],
        },
    }
    with pytest.raises(ChartValidationError) as exc_info:
        validate_chart_spec(
            json.dumps(bad_spec),
            allowed_metrics=_ALLOWED_METRICS,
            allowed_dimensions=_ALLOWED_DIMS,
        )
    # region is a dimension, not in allowed_metrics → rejected before any query.
    assert "metric" in exc_info.value.reason.lower()


def test_direct_validator_rejects_inline_query() -> None:
    """A spec with query.query (inline dataset) on the AI path is rejected."""
    inline_spec: dict[str, Any] = {
        "version": "1",
        "type": "bar",
        "query": {
            "query": {
                "dimensions": ["region"],
                "metrics": [{"function": "sum", "column": "amount", "alias": "total"}],
            },
            "metric_refs": [],
        },
        "encoding": {
            "x": "regional_sales.region",
            "series": [{"field": "regional_sales.total_amount"}],
        },
        "options": {"title": None},
    }
    with pytest.raises(ChartValidationError) as exc_info:
        validate_chart_spec(
            json.dumps(inline_spec),
            allowed_metrics=_ALLOWED_METRICS,
            allowed_dimensions=_ALLOWED_DIMS,
        )
    reason = exc_info.value.reason.lower()
    assert "metric_refs" in reason or "inline" in reason or "query" in reason


def test_direct_validator_case_insensitive_allow_list() -> None:
    """Allow-list check is case-insensitive for metrics and dimensions."""
    # FieldName pattern requires letter/number/underscore/dot — use valid casing only
    lower_spec: dict[str, Any] = {
        "version": "1",
        "type": "bar",
        "query": {"metric_refs": ["regional_sales.total_amount"]},
        "encoding": {
            "x": "regional_sales.region",
            "series": [{"field": "regional_sales.total_amount"}],
        },
        "options": {"title": None},
    }
    # Pass upper-cased allowed sets (the validator should normalise)
    result = validate_chart_spec(
        json.dumps(lower_spec),
        allowed_metrics={"REGIONAL_SALES.TOTAL_AMOUNT"},
        allowed_dimensions={"REGIONAL_SALES.REGION"},
    )
    assert result.type == "bar"


# ===========================================================================
# Grounding context unit tests
# ===========================================================================


def test_grounding_builds_metric_set() -> None:
    """build_chart_grounding_context extracts measure names as allowed_metrics."""
    ctx = build_chart_grounding_context(_FAKE_META)
    assert "regional_sales.total_amount" in ctx.allowed_metrics
    assert "regional_sales.avg_share" in ctx.allowed_metrics


def test_grounding_builds_dimension_set() -> None:
    """build_chart_grounding_context extracts dimension names as allowed_dimensions."""
    ctx = build_chart_grounding_context(_FAKE_META)
    assert "regional_sales.region" in ctx.allowed_dimensions
    assert "regional_sales.sales_rank" in ctx.allowed_dimensions


def test_grounding_semantic_text_contains_metric_names() -> None:
    """The semantic text includes governed metric names so the LLM can reference them."""
    ctx = build_chart_grounding_context(_FAKE_META)
    assert "regional_sales.total_amount" in ctx.semantic_text
    assert "regional_sales.avg_share" in ctx.semantic_text


def test_grounding_semantic_text_contains_dimension_names() -> None:
    """The semantic text includes governed dimension names."""
    ctx = build_chart_grounding_context(_FAKE_META)
    assert "regional_sales.region" in ctx.semantic_text
    assert "regional_sales.sales_rank" in ctx.semantic_text


def test_grounding_empty_meta_returns_sentinel_text() -> None:
    """An empty meta returns a sentinel text and empty allow-lists."""
    ctx = build_chart_grounding_context({"cubes": []})
    assert "no governed objects" in ctx.semantic_text.lower()
    assert len(ctx.allowed_metrics) == 0
    assert len(ctx.allowed_dimensions) == 0


def test_grounding_semantic_text_does_not_contain_physical_table() -> None:
    """The chart grounding text must NOT surface raw physical table names to the LLM.

    For the NL→Chart path, the LLM works exclusively with governed metric/dimension
    identifiers — it never needs to know physical table names.
    """
    ctx = build_chart_grounding_context(_FAKE_META)
    # Physical table name must NOT appear in the chart semantic context.
    assert "serving_regional_sales" not in ctx.semantic_text


# ===========================================================================
# Ensure query is NEVER called on any rejection path
# ===========================================================================


@pytest.mark.parametrize(
    "bad_output",
    [
        "UNSATISFIABLE",
        "not json at all",
        '["array", "not", "object"]',
        json.dumps({**_VALID_SPEC_DICT, "extra_key": True}),
        json.dumps({**_VALID_SPEC_DICT, "type": "heatmap"}),
        json.dumps(
            {
                "version": "1",
                "type": "bar",
                "query": {"metric_refs": ["regional_sales.fake_metric"]},
                "encoding": {
                    "x": "regional_sales.region",
                    "series": [{"field": "regional_sales.fake_metric"}],
                },
                "options": {"title": None},
            }
        ),
        json.dumps(
            {
                "version": "1",
                "type": "bar",
                "query": {"metric_refs": ["regional_sales.total_amount"]},
                "encoding": {
                    "x": "regional_sales.not_a_dim",
                    "series": [{"field": "regional_sales.total_amount"}],
                },
                "options": {"title": None},
            }
        ),
    ],
    ids=[
        "unsatisfiable",
        "not-json",
        "json-array",
        "extra-field",
        "bad-chart-type",
        "ungrounded-metric",
        "ungrounded-dimension",
    ],
)
@pytest.mark.asyncio
async def test_query_never_called_on_rejection(bad_output: str) -> None:
    """On every rejection path, SemanticLayerClient.query is never called."""
    ctx = _make_ctx()
    svc, _, _, mock_query = _make_service(
        gateway_response=_make_llm_response(bad_output)
    )

    with pytest.raises(ChartValidationError):
        await svc.generate(ctx, request="some request")

    mock_query.assert_not_called(), (
        f"query was called despite validation failure for output: {bad_output!r}"
    )
