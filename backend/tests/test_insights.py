"""Tests for Phase 4, Task 4.5 — Insight summaries & dataset suggestions.

Strategy
--------
All tests run entirely in-process.  External boundaries are mocked:
  1. LLMGateway.complete  — returns controlled text / JSON strings.
  2. ClickHouseDatasetService — mocked for profiling queries.
  3. DatasetService.get_for_tenant — mocked for ownership enforcement.

No real network calls, live ClickHouse, or LLM provider are used.

Test structure
--------------
Part A — no-invented-numbers guardrail (pure function unit tests):
  - numbers in data → pass
  - rounded numbers → pass (rounding tolerance)
  - number with formatting (thousands sep / currency / %) → pass
  - number NOT in data → raise InsightGuardrailError
  - empty summary (no numbers) → pass
  - multiple numbers, one invented → raise

Part B — InsightService integration tests (mock gateway):
  - valid summary whose numbers are all in the data → returns summary
  - summary with invented number: first attempt fails, second attempt passes → returns
  - summary with invented number on both attempts → raises InsightGuardrailError
  - empty result set → returns canned message without calling gateway
  - tenant context flows through (no cross-tenant leak)

Part C — SuggestionsService integration tests (mock gateway + ClickHouse):
  - valid profile → returns ≥1 valid suggestions
  - suggestion referencing non-existent column → dropped
  - all suggestions invalid → empty list with note (no 500)
  - dataset not owned by tenant → 404 propagates (get_for_tenant raises)
  - tenant context enforced: get_for_tenant called with server-resolved ctx

Part D — API endpoint tests via TestClient (dependency overrides):
  - POST /ai/insights with valid data → 200 with summary
  - POST /ai/insights with guardrail failure → 422
  - POST /ai/datasets/{id}/suggestions with valid data → 200 with suggestions
  - POST /ai/datasets/{id}/suggestions with non-existent dataset → 404
"""
from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.ai.gateway.gateway import LLMGateway
from app.ai.gateway.loader import PromptLoader
from app.ai.gateway.provider import LLMResponse
from app.ai.insights.guardrail import (
    InsightGuardrailError,
    _extract_numbers,
    _extract_reference_values,
    _is_traceable,
    verify_no_invented_numbers,
)
from app.ai.insights.suggestion_validator import validate_suggestions
from app.ai.insights.suggestions import SuggestionsService
from app.ai.insights.summary import InsightService
from app.schemas.chart import ChartSpec
from app.tenancy.context import TenantContext
from app.tenancy.resources import resources_for_slug

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


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
        model="test-model",
        usage={"input_tokens": 50, "output_tokens": 40},
    )


def _make_prompts_loader() -> PromptLoader:
    """Return a real PromptLoader pointing at the actual prompts directory."""
    import pathlib
    prompts_dir = pathlib.Path(__file__).parent.parent / "app" / "ai" / "prompts"
    return PromptLoader(str(prompts_dir))


# ===========================================================================
# Part A — no-invented-numbers guardrail (pure function tests)
# ===========================================================================


class TestExtractNumbers:
    """Unit tests for the _extract_numbers helper."""

    def test_plain_integer(self) -> None:
        assert 42.0 in _extract_numbers("There are 42 items.")

    def test_decimal(self) -> None:
        assert 3.14 in _extract_numbers("The value is 3.14 units.")

    def test_thousands_separator(self) -> None:
        assert 1234.0 in _extract_numbers("Revenue was 1,234.")

    def test_currency_prefix(self) -> None:
        result = _extract_numbers("Total is $1,500.00.")
        assert 1500.0 in result

    def test_percentage_suffix(self) -> None:
        result = _extract_numbers("Growth was 12.5%.")
        assert 12.5 in result

    def test_negative_number(self) -> None:
        result = _extract_numbers("Loss of -45 units.")
        assert -45.0 in result

    def test_no_numbers(self) -> None:
        assert _extract_numbers("No data available.") == []

    def test_multiple_numbers(self) -> None:
        result = _extract_numbers("Sold 100 items for $2,500.50.")
        assert 100.0 in result
        assert 2500.5 in result

    def test_scientific_notation_lowercase_e(self) -> None:
        # Regression (C1): "2.4e6" must be extracted, else a hallucinated number
        # in scientific notation would silently bypass the guardrail.
        assert 2_400_000.0 in _extract_numbers("Revenue was 2.4e6 this quarter.")

    def test_scientific_notation_uppercase_e_and_sign(self) -> None:
        assert 1_500_000_000.0 in _extract_numbers("It reached 1.5E+9 units.")
        assert 0.0072 in _extract_numbers("The rate was 7.2e-3 overall.")

    def test_scientific_notation_ungrounded_is_rejected(self) -> None:
        # Full guardrail path: a sci-notation number absent from the data is caught.
        with pytest.raises(InsightGuardrailError):
            verify_no_invented_numbers(
                "Revenue was 9.9e9.",
                columns=["amount"],
                rows=[[100.0], [200.0]],
            )


class TestExtractReferenceValues:
    """Unit tests for _extract_reference_values helper."""

    def test_integer_values(self) -> None:
        refs = _extract_reference_values(["count"], [[42], [100]])
        assert 42.0 in refs
        assert 100.0 in refs

    def test_float_values(self) -> None:
        refs = _extract_reference_values(["revenue"], [[142500.50]])
        assert 142500.50 in refs

    def test_bool_values_skipped(self) -> None:
        refs = _extract_reference_values(["flag"], [[True], [False]])
        assert 1.0 not in refs
        assert 0.0 not in refs

    def test_string_numeric(self) -> None:
        refs = _extract_reference_values(["val"], [["123.45"]])
        assert 123.45 in refs

    def test_non_numeric_string_skipped(self) -> None:
        refs = _extract_reference_values(["name"], [["EMEA"]])
        assert len(refs) == 0

    def test_mixed_row(self) -> None:
        refs = _extract_reference_values(["region", "revenue"], [["EMEA", 500.0]])
        assert 500.0 in refs
        assert len(refs) == 1


class TestIsTraceable:
    """Unit tests for _is_traceable helper."""

    def test_exact_match(self) -> None:
        assert _is_traceable(100.0, [100.0, 200.0])

    def test_rounded_match(self) -> None:
        # 142500.876 rounded to 0 decimals = 142501
        assert _is_traceable(142501.0, [142500.876])

    def test_no_match(self) -> None:
        assert not _is_traceable(9999.0, [100.0, 200.0])

    def test_empty_references(self) -> None:
        assert not _is_traceable(5.0, [])

    def test_scaled_match_thousands(self) -> None:
        # 1500 / 1000 = 1.5 — summary says "1.5K" (we'd extract 1.5)
        assert _is_traceable(1.5, [1500.0])

    def test_no_spurious_small_scale_match(self) -> None:
        # 9999 / 100 ~ 100 but 100x is NOT a valid scale factor;
        # should not spuriously match 100.0
        assert not _is_traceable(9999.0, [100.0])

    def test_no_spurious_match(self) -> None:
        # 9999 is nowhere near 100, 200 even after scaling
        assert not _is_traceable(9999.0, [100.0, 200.0])


class TestVerifyNoInventedNumbers:
    """Unit tests for the main public guardrail function."""

    def test_numbers_all_in_data_passes(self) -> None:
        verify_no_invented_numbers(
            "Revenue was $1,234 across 3 regions.",
            columns=["region", "revenue", "count"],
            rows=[["EMEA", 1234, 3]],
        )

    def test_rounded_number_passes(self) -> None:
        verify_no_invented_numbers(
            "Total revenue was approximately 142,501.",
            columns=["revenue"],
            rows=[[142500.876]],
        )

    def test_currency_formatted_number_passes(self) -> None:
        verify_no_invented_numbers(
            "Total was $2,500.",
            columns=["revenue"],
            rows=[[2500.0]],
        )

    def test_percentage_formatted_number_passes(self) -> None:
        verify_no_invented_numbers(
            "Growth was 12%.",
            columns=["growth_pct"],
            rows=[[12.0]],
        )

    def test_invented_number_raises(self) -> None:
        with pytest.raises(InsightGuardrailError) as exc_info:
            verify_no_invented_numbers(
                "Revenue was $9,999.",
                columns=["revenue"],
                rows=[[1234.0]],
            )
        reason = exc_info.value.reason.lower()
        assert "cannot be verified" in reason or "not" in reason

    def test_no_numbers_in_summary_passes(self) -> None:
        verify_no_invented_numbers(
            "Sales performance was strong across all regions.",
            columns=["region", "revenue"],
            rows=[["EMEA", 1000.0]],
        )

    def test_multiple_numbers_one_invented_raises(self) -> None:
        # 100 is in data, 9999 is not
        with pytest.raises(InsightGuardrailError):
            verify_no_invented_numbers(
                "There were 100 items and 9,999 orders.",
                columns=["items"],
                rows=[[100]],
            )

    def test_empty_rows_with_numbers_raises(self) -> None:
        with pytest.raises(InsightGuardrailError):
            verify_no_invented_numbers(
                "Total was 500.",
                columns=["revenue"],
                rows=[],
            )

    def test_empty_rows_without_numbers_passes(self) -> None:
        verify_no_invented_numbers(
            "No data available.",
            columns=["revenue"],
            rows=[],
        )


# ===========================================================================
# Part B — InsightService integration tests
# ===========================================================================


def _make_insight_service(
    *,
    gateway_responses: list[LLMResponse] | None = None,
) -> tuple[InsightService, MagicMock]:
    """Build an InsightService with a mocked gateway."""
    loader = _make_prompts_loader()
    mock_gateway = MagicMock(spec=LLMGateway)

    responses = gateway_responses or [_make_llm_response("Revenue was 1,234.")]
    mock_gateway.complete = AsyncMock(side_effect=responses)

    svc = InsightService(gateway=mock_gateway, prompt_loader=loader)  # type: ignore[arg-type]
    return svc, mock_gateway


@pytest.mark.asyncio
async def test_insight_valid_summary_returned() -> None:
    """Valid summary with numbers from data → returned as-is."""
    ctx = _make_ctx()
    svc, _ = _make_insight_service(
        gateway_responses=[_make_llm_response("Revenue was 1,234 in region EMEA.")]
    )

    summary = await svc.summarise(
        ctx,
        columns=["region", "revenue"],
        rows=[["EMEA", 1234]],
    )
    assert "1,234" in summary or "1234" in summary


@pytest.mark.asyncio
async def test_insight_first_attempt_fails_second_passes() -> None:
    """First summary has invented number; second has real number → returns second."""
    ctx = _make_ctx()
    svc, mock_gw = _make_insight_service(
        gateway_responses=[
            _make_llm_response("Revenue was 9,999."),    # invented
            _make_llm_response("Revenue was 1,234."),    # correct
        ]
    )

    summary = await svc.summarise(
        ctx,
        columns=["revenue"],
        rows=[[1234]],
    )

    assert "1,234" in summary or "1234" in summary
    assert mock_gw.complete.call_count == 2


@pytest.mark.asyncio
async def test_insight_both_attempts_fail_raises_guardrail_error() -> None:
    """Both attempts produce invented numbers → InsightGuardrailError raised."""
    ctx = _make_ctx()
    svc, _ = _make_insight_service(
        gateway_responses=[
            _make_llm_response("Revenue was 9,999."),  # invented
            _make_llm_response("Revenue was 8,888."),  # still invented
        ]
    )

    with pytest.raises(InsightGuardrailError):
        await svc.summarise(
            ctx,
            columns=["revenue"],
            rows=[[1234]],
        )


@pytest.mark.asyncio
async def test_insight_empty_result_set_returns_canned_message() -> None:
    """Empty result set → canned 'no data' message without calling gateway."""
    ctx = _make_ctx()
    svc, mock_gw = _make_insight_service()

    summary = await svc.summarise(
        ctx,
        columns=["revenue"],
        rows=[],
    )

    assert "no data" in summary.lower() or "available" in summary.lower()
    mock_gw.complete.assert_not_called()


@pytest.mark.asyncio
async def test_insight_tenant_context_passed_to_gateway() -> None:
    """Gateway is called with the server-resolved TenantContext."""
    ctx = _make_ctx("myorg")
    svc, mock_gw = _make_insight_service(
        gateway_responses=[_make_llm_response("Revenue was 100.")]
    )

    await svc.summarise(ctx, columns=["revenue"], rows=[[100]])

    call_kwargs = mock_gw.complete.call_args
    # ctx is passed as keyword argument 'ctx'
    assert call_kwargs.kwargs["ctx"].tenant_id == ctx.tenant_id


@pytest.mark.asyncio
async def test_insight_context_hint_reaches_prompt() -> None:
    """The context_hint (I1) is actually forwarded into the LLM user message."""
    ctx = _make_ctx()
    svc, mock_gw = _make_insight_service(
        gateway_responses=[_make_llm_response("Revenue was 100.")]
    )

    await svc.summarise(
        ctx, columns=["revenue"], rows=[[100]], context_hint="Q3 Regional Sales"
    )

    llm_request = mock_gw.complete.call_args.args[0]
    assert "Q3 Regional Sales" in llm_request.user_message


@pytest.mark.asyncio
async def test_insight_no_cross_tenant() -> None:
    """Two tenants' summarise calls use their own separate contexts."""
    ctx_a = _make_ctx("alpha")
    ctx_b = _make_ctx("beta")

    loader = _make_prompts_loader()
    call_contexts: list[TenantContext] = []

    async def _capture_ctx(request: Any, *, ctx: TenantContext) -> LLMResponse:
        call_contexts.append(ctx)
        return _make_llm_response("Revenue was 100.")

    mock_gw = MagicMock(spec=LLMGateway)
    mock_gw.complete = AsyncMock(side_effect=_capture_ctx)

    svc = InsightService(gateway=mock_gw, prompt_loader=loader)  # type: ignore[arg-type]

    await svc.summarise(ctx_a, columns=["revenue"], rows=[[100]])
    await svc.summarise(ctx_b, columns=["revenue"], rows=[[100]])

    assert len(call_contexts) == 2
    assert call_contexts[0].tenant_id == ctx_a.tenant_id
    assert call_contexts[1].tenant_id == ctx_b.tenant_id
    assert call_contexts[0].tenant_id != call_contexts[1].tenant_id


# ===========================================================================
# Part C — SuggestionsService integration tests
# ===========================================================================


def _make_dataset(
    tenant_id: str,
    dataset_id: uuid.UUID | None = None,
) -> Any:
    """Create a minimal mock Dataset object."""
    from app.models.dataset import Dataset
    ds = MagicMock(spec=Dataset)
    ds.id = dataset_id or uuid.uuid4()
    ds.tenant_id = uuid.UUID(tenant_id)
    ds.name = "test_dataset.csv"
    return ds


def _make_valid_suggestion_json(
    dataset_id: str,
    col_name: str = "region",
    metric_col: str = "revenue",
    alias: str = "total_revenue",
) -> dict[str, Any]:
    """Build a valid suggestion dict the LLM might return."""
    return {
        "title": "Revenue by Region",
        "rationale": "Shows how revenue is distributed across regions.",
        "spec": {
            "version": "1",
            "type": "bar",
            "query": {
                "dataset_id": dataset_id,
                "query": {
                    "dimensions": [col_name],
                    "metrics": [
                        {
                            "function": "sum",
                            "column": metric_col,
                            "alias": alias,
                        }
                    ],
                    "filters": [],
                    "limit": 1000,
                },
            },
            "encoding": {
                "x": col_name,
                "series": [{"field": alias, "name": "Total Revenue"}],
            },
            "options": {
                "title": "Revenue by Region",
                "stacked": False,
                "show_legend": True,
            },
        },
    }


class TestValidateSuggestions:
    """Unit tests for the suggestions validator."""

    def test_valid_suggestion_passes(self) -> None:
        dataset_id = str(uuid.uuid4())
        raw = [_make_valid_suggestion_json(dataset_id, "region", "revenue", "total_rev")]
        result = validate_suggestions(
            raw,
            allowed_columns={"region", "revenue"},
            dataset_id_str=dataset_id,
        )
        assert len(result) == 1
        assert result[0].title == "Revenue by Region"
        assert isinstance(result[0].spec, ChartSpec)

    def test_non_existent_column_dropped(self) -> None:
        dataset_id = str(uuid.uuid4())
        raw = [_make_valid_suggestion_json(dataset_id, "ghost_col", "revenue", "total_rev")]
        result = validate_suggestions(
            raw,
            allowed_columns={"region", "revenue"},  # ghost_col not here
            dataset_id_str=dataset_id,
        )
        assert len(result) == 0

    def test_non_existent_metric_column_dropped(self) -> None:
        dataset_id = str(uuid.uuid4())
        raw = [_make_valid_suggestion_json(dataset_id, "region", "fake_col", "total_rev")]
        result = validate_suggestions(
            raw,
            allowed_columns={"region", "revenue"},  # fake_col not here
            dataset_id_str=dataset_id,
        )
        assert len(result) == 0

    def test_wrong_dataset_id_dropped(self) -> None:
        dataset_id = str(uuid.uuid4())
        other_id = str(uuid.uuid4())
        raw = [_make_valid_suggestion_json(other_id, "region", "revenue", "total_rev")]
        result = validate_suggestions(
            raw,
            allowed_columns={"region", "revenue"},
            dataset_id_str=dataset_id,
        )
        assert len(result) == 0

    def test_missing_title_dropped(self) -> None:
        dataset_id = str(uuid.uuid4())
        suggestion = _make_valid_suggestion_json(dataset_id, "region", "revenue", "total_rev")
        del suggestion["title"]
        result = validate_suggestions(
            [suggestion],
            allowed_columns={"region", "revenue"},
            dataset_id_str=dataset_id,
        )
        assert len(result) == 0

    def test_missing_spec_dropped(self) -> None:
        dataset_id = str(uuid.uuid4())
        raw = [{"title": "Test", "rationale": "Testing"}]
        result = validate_suggestions(
            raw,
            allowed_columns={"region"},
            dataset_id_str=dataset_id,
        )
        assert len(result) == 0

    def test_metric_refs_path_dropped(self) -> None:
        """Suggestion using metric_refs (semantic layer path) must be dropped."""
        dataset_id = str(uuid.uuid4())
        bad_spec = {
            "title": "Bad",
            "rationale": "Uses metric_refs not allowed for suggestions.",
            "spec": {
                "version": "1",
                "type": "bar",
                "query": {
                    "metric_refs": ["some.metric"],
                },
                "encoding": {
                    "x": "region",
                    "series": [{"field": "some.metric"}],
                },
                "options": {"title": None, "stacked": False, "show_legend": True},
            },
        }
        result = validate_suggestions(
            [bad_spec],
            allowed_columns={"region"},
            dataset_id_str=dataset_id,
        )
        assert len(result) == 0

    def test_series_field_not_alias_dropped(self) -> None:
        """Series field that doesn't match any metric alias is dropped."""
        dataset_id = str(uuid.uuid4())
        suggestion = _make_valid_suggestion_json(dataset_id, "region", "revenue", "total_rev")
        # Modify series field to something not matching the alias
        suggestion["spec"]["encoding"]["series"][0]["field"] = "wrong_alias"
        result = validate_suggestions(
            [suggestion],
            allowed_columns={"region", "revenue"},
            dataset_id_str=dataset_id,
        )
        assert len(result) == 0

    def test_extra_field_in_spec_dropped(self) -> None:
        """Spec with an unknown extra field is dropped (strict mode)."""
        dataset_id = str(uuid.uuid4())
        suggestion = _make_valid_suggestion_json(dataset_id, "region", "revenue", "total_rev")
        suggestion["spec"]["injected_field"] = "evil"
        result = validate_suggestions(
            [suggestion],
            allowed_columns={"region", "revenue"},
            dataset_id_str=dataset_id,
        )
        assert len(result) == 0

    def test_empty_input_returns_empty(self) -> None:
        result = validate_suggestions(
            [],
            allowed_columns={"region"},
            dataset_id_str=str(uuid.uuid4()),
        )
        assert result == []

    def test_mixed_valid_and_invalid(self) -> None:
        """Only valid suggestions survive; invalid ones are dropped."""
        dataset_id = str(uuid.uuid4())
        valid = _make_valid_suggestion_json(dataset_id, "region", "revenue", "total_rev")
        invalid = _make_valid_suggestion_json(dataset_id, "ghost_col", "revenue", "total_rev")
        result = validate_suggestions(
            [valid, invalid],
            allowed_columns={"region", "revenue"},
            dataset_id_str=dataset_id,
        )
        assert len(result) == 1
        assert result[0].title == "Revenue by Region"


@pytest.mark.asyncio
async def test_suggestions_valid_profile_returns_suggestions() -> None:
    """Valid profile → at least one suggestion returned."""
    ctx = _make_ctx()
    dataset_id = uuid.uuid4()
    dataset = _make_dataset(ctx.tenant_id, dataset_id)

    suggestion_json = _make_valid_suggestion_json(
        str(dataset_id), "region", "revenue", "total_rev"
    )
    llm_response = _make_llm_response(json.dumps([suggestion_json]))

    mock_gateway = MagicMock(spec=LLMGateway)
    mock_gateway.complete = AsyncMock(return_value=llm_response)

    # Mock DatasetService
    mock_dataset_svc = MagicMock()
    mock_dataset_svc.get_for_tenant = AsyncMock(return_value=dataset)

    # Mock ClickHouseDatasetService with profiling responses
    mock_ch_svc = MagicMock()
    # DESCRIBE returns rows: [name, type, ...]
    describe_result = MagicMock()
    describe_result.rows = [("region", "String"), ("revenue", "Float64")]
    # COUNT(*) returns [[row_count]]
    count_result = MagicMock()
    count_result.rows = [[1000]]
    # Per-column: distinct count + stats
    distinct_result = MagicMock()
    distinct_result.rows = [[5]]
    stats_result = MagicMock()
    stats_result.rows = [[100.0, 5000.0, 2500.0]]
    sample_result = MagicMock()
    sample_result.rows = [["EMEA"], ["APAC"], ["AMER"]]

    def _run_query(ctx: Any, sql: str, **kwargs: Any) -> Any:
        if "DESCRIBE" in sql:
            return describe_result
        if "count(*)" in sql.lower():
            return count_result
        if "uniq(" in sql.lower():
            return distinct_result
        if "min(" in sql.lower():
            return stats_result
        if "DISTINCT" in sql:
            return sample_result
        return MagicMock(rows=[])

    mock_ch_svc.run_read_only_query = MagicMock(side_effect=_run_query)

    loader = _make_prompts_loader()
    svc = SuggestionsService(
        gateway=mock_gateway,  # type: ignore[arg-type]
        prompt_loader=loader,
        dataset_service=mock_dataset_svc,  # type: ignore[arg-type]
        ch_svc=mock_ch_svc,  # type: ignore[arg-type]
    )

    suggestions = await svc.suggest(ctx, dataset_id=dataset_id)
    assert len(suggestions) >= 1
    assert suggestions[0].title == "Revenue by Region"
    assert isinstance(suggestions[0].spec, ChartSpec)


@pytest.mark.asyncio
async def test_suggestions_invalid_column_dropped() -> None:
    """Suggestion referencing a non-existent column is dropped."""
    ctx = _make_ctx()
    dataset_id = uuid.uuid4()
    dataset = _make_dataset(ctx.tenant_id, dataset_id)

    # Suggestion references "ghost_col" which is not in the profile
    bad_suggestion = _make_valid_suggestion_json(
        str(dataset_id), "ghost_col", "revenue", "total_rev"
    )
    llm_response = _make_llm_response(json.dumps([bad_suggestion]))

    mock_gateway = MagicMock(spec=LLMGateway)
    mock_gateway.complete = AsyncMock(return_value=llm_response)

    mock_dataset_svc = MagicMock()
    mock_dataset_svc.get_for_tenant = AsyncMock(return_value=dataset)

    mock_ch_svc = MagicMock()
    describe_result = MagicMock()
    describe_result.rows = [("region", "String"), ("revenue", "Float64")]
    count_result = MagicMock()
    count_result.rows = [[100]]
    distinct_result = MagicMock()
    distinct_result.rows = [[5]]
    stats_result = MagicMock()
    stats_result.rows = [[100.0, 5000.0, 2500.0]]
    sample_result = MagicMock()
    sample_result.rows = [["EMEA"]]

    def _run_query(ctx: Any, sql: str, **kwargs: Any) -> Any:
        if "DESCRIBE" in sql:
            return describe_result
        if "count(*)" in sql.lower():
            return count_result
        if "uniq(" in sql.lower():
            return distinct_result
        if "min(" in sql.lower():
            return stats_result
        return sample_result

    mock_ch_svc.run_read_only_query = MagicMock(side_effect=_run_query)

    loader = _make_prompts_loader()
    svc = SuggestionsService(
        gateway=mock_gateway,  # type: ignore[arg-type]
        prompt_loader=loader,
        dataset_service=mock_dataset_svc,  # type: ignore[arg-type]
        ch_svc=mock_ch_svc,  # type: ignore[arg-type]
    )

    suggestions = await svc.suggest(ctx, dataset_id=dataset_id)
    # ghost_col not in {region, revenue} → suggestion dropped
    assert len(suggestions) == 0


@pytest.mark.asyncio
async def test_suggestions_all_invalid_returns_empty() -> None:
    """All suggestions invalid → empty list returned (no exception)."""
    ctx = _make_ctx()
    dataset_id = uuid.uuid4()
    dataset = _make_dataset(ctx.tenant_id, dataset_id)

    # Return malformed JSON (will parse as non-list → empty)
    llm_response = _make_llm_response("not valid json")

    mock_gateway = MagicMock(spec=LLMGateway)
    mock_gateway.complete = AsyncMock(return_value=llm_response)

    mock_dataset_svc = MagicMock()
    mock_dataset_svc.get_for_tenant = AsyncMock(return_value=dataset)

    mock_ch_svc = MagicMock()
    describe_result = MagicMock()
    describe_result.rows = [("region", "String")]
    count_result = MagicMock()
    count_result.rows = [[50]]
    distinct_result = MagicMock()
    distinct_result.rows = [[3]]
    sample_result = MagicMock()
    sample_result.rows = [["A"]]

    def _run_query(ctx: Any, sql: str, **kwargs: Any) -> Any:
        if "DESCRIBE" in sql:
            return describe_result
        if "count(*)" in sql.lower():
            return count_result
        if "uniq(" in sql.lower():
            return distinct_result
        return sample_result

    mock_ch_svc.run_read_only_query = MagicMock(side_effect=_run_query)

    loader = _make_prompts_loader()
    svc = SuggestionsService(
        gateway=mock_gateway,  # type: ignore[arg-type]
        prompt_loader=loader,
        dataset_service=mock_dataset_svc,  # type: ignore[arg-type]
        ch_svc=mock_ch_svc,  # type: ignore[arg-type]
    )

    suggestions = await svc.suggest(ctx, dataset_id=dataset_id)
    assert suggestions == []


@pytest.mark.asyncio
async def test_suggestions_dataset_not_owned_raises_404() -> None:
    """Dataset not owned by the tenant → 404 propagates from get_for_tenant."""
    ctx = _make_ctx()
    dataset_id = uuid.uuid4()

    mock_dataset_svc = MagicMock()
    mock_dataset_svc.get_for_tenant = AsyncMock(
        side_effect=HTTPException(status_code=404, detail="Dataset not found")
    )

    mock_gateway = MagicMock(spec=LLMGateway)
    mock_ch_svc = MagicMock()
    loader = _make_prompts_loader()

    svc = SuggestionsService(
        gateway=mock_gateway,  # type: ignore[arg-type]
        prompt_loader=loader,
        dataset_service=mock_dataset_svc,  # type: ignore[arg-type]
        ch_svc=mock_ch_svc,  # type: ignore[arg-type]
    )

    with pytest.raises(HTTPException) as exc_info:
        await svc.suggest(ctx, dataset_id=dataset_id)

    assert exc_info.value.status_code == 404
    # Gateway must not have been called (dataset never profiled)
    mock_gateway.complete.assert_not_called()


@pytest.mark.asyncio
async def test_suggestions_get_for_tenant_called_with_server_ctx() -> None:
    """get_for_tenant is called with the server-resolved ctx (not from body)."""
    ctx = _make_ctx("widgetco")
    dataset_id = uuid.uuid4()
    dataset = _make_dataset(ctx.tenant_id, dataset_id)

    captured_ctx: list[TenantContext] = []

    async def _capture(c: TenantContext, did: uuid.UUID) -> Any:
        captured_ctx.append(c)
        return dataset

    mock_dataset_svc = MagicMock()
    mock_dataset_svc.get_for_tenant = AsyncMock(side_effect=_capture)

    mock_gateway = MagicMock(spec=LLMGateway)
    mock_gateway.complete = AsyncMock(return_value=_make_llm_response("[]"))

    mock_ch_svc = MagicMock()
    describe_result = MagicMock()
    describe_result.rows = [("region", "String")]
    count_result = MagicMock()
    count_result.rows = [[10]]
    distinct_result = MagicMock()
    distinct_result.rows = [[2]]
    sample_result = MagicMock()
    sample_result.rows = [["A"]]

    def _run_query(ctx: Any, sql: str, **kwargs: Any) -> Any:
        if "DESCRIBE" in sql:
            return describe_result
        if "count(*)" in sql.lower():
            return count_result
        if "uniq(" in sql.lower():
            return distinct_result
        return sample_result

    mock_ch_svc.run_read_only_query = MagicMock(side_effect=_run_query)

    loader = _make_prompts_loader()
    svc = SuggestionsService(
        gateway=mock_gateway,  # type: ignore[arg-type]
        prompt_loader=loader,
        dataset_service=mock_dataset_svc,  # type: ignore[arg-type]
        ch_svc=mock_ch_svc,  # type: ignore[arg-type]
    )

    await svc.suggest(ctx, dataset_id=dataset_id)

    assert len(captured_ctx) == 1
    assert captured_ctx[0].tenant_id == ctx.tenant_id
    assert captured_ctx[0].clickhouse_db == ctx.clickhouse_db


# ===========================================================================
# Part D — API endpoint tests via TestClient
# ===========================================================================


def _make_test_client() -> TestClient:
    """Build a TestClient with auth bypassed."""
    from app.main import app
    from app.tenancy.context import get_tenant_context

    test_ctx = _make_ctx("test-tenant")

    async def _mock_tenant_ctx() -> TenantContext:
        return test_ctx

    app.dependency_overrides[get_tenant_context] = _mock_tenant_ctx
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.asyncio
async def test_api_insights_200() -> None:
    """POST /ai/insights with valid data returns 200 with a summary."""
    from app.ai.insights.summary import get_insight_service
    from app.main import app

    test_ctx = _make_ctx("apitest")

    async def _mock_ctx() -> TenantContext:
        return test_ctx

    mock_svc = MagicMock()
    mock_svc.summarise = AsyncMock(return_value="Revenue was 1,234 across EMEA.")

    app.dependency_overrides[get_insight_service] = lambda: mock_svc
    from app.tenancy.context import get_tenant_context
    app.dependency_overrides[get_tenant_context] = _mock_ctx

    try:
        client = TestClient(app, raise_server_exceptions=True)
        response = client.post(
            "/api/v1/ai/insights",
            json={
                "columns": ["region", "revenue"],
                "rows": [["EMEA", 1234]],
                "context_hint": "Dashboard: Sales Overview",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "summary" in data
        assert "1,234" in data["summary"] or "1234" in data["summary"]
    finally:
        app.dependency_overrides.pop(get_insight_service, None)
        app.dependency_overrides.pop(get_tenant_context, None)


@pytest.mark.asyncio
async def test_api_insights_422_on_guardrail_failure() -> None:
    """POST /ai/insights when guardrail fires → 422."""
    from app.ai.insights.summary import get_insight_service
    from app.main import app
    from app.tenancy.context import get_tenant_context

    test_ctx = _make_ctx("apitest422")

    async def _mock_ctx() -> TenantContext:
        return test_ctx

    mock_svc = MagicMock()
    mock_svc.summarise = AsyncMock(
        side_effect=InsightGuardrailError(
            "The generated summary contains numbers that cannot be verified "
            "against the result set data. Please try again."
        )
    )

    app.dependency_overrides[get_insight_service] = lambda: mock_svc
    app.dependency_overrides[get_tenant_context] = _mock_ctx

    try:
        client = TestClient(app, raise_server_exceptions=True)
        response = client.post(
            "/api/v1/ai/insights",
            json={"columns": ["revenue"], "rows": [[1234]]},
        )
        assert response.status_code == 422
    finally:
        app.dependency_overrides.pop(get_insight_service, None)
        app.dependency_overrides.pop(get_tenant_context, None)


@pytest.mark.asyncio
async def test_api_suggestions_200() -> None:
    """POST /ai/datasets/{id}/suggestions with valid data returns 200."""
    from app.ai.insights.suggestion_validator import ValidatedSuggestion
    from app.ai.insights.suggestions import get_suggestions_service
    from app.main import app
    from app.tenancy.context import get_tenant_context

    dataset_id = uuid.uuid4()
    test_ctx = _make_ctx("apisugtest")

    async def _mock_ctx() -> TenantContext:
        return test_ctx

    # Provide a real ChartSpec for JSON serialization
    from app.schemas.chart import ChartEncoding, ChartOptions, ChartQuery, SeriesEncoding
    from app.schemas.query import Metric, QueryRequest
    real_spec = ChartSpec(
        type="bar",
        query=ChartQuery(
            dataset_id=dataset_id,
            query=QueryRequest(
                dimensions=["region"],
                metrics=[Metric(function="sum", column="revenue", alias="total_rev")],
            ),
        ),
        encoding=ChartEncoding(
            x="region",
            series=[SeriesEncoding(field="total_rev", name="Total Rev")],
        ),
        options=ChartOptions(title="Revenue by Region"),
    )
    mock_suggestion = ValidatedSuggestion(
        title="Revenue by Region",
        rationale="Shows revenue distribution.",
        spec=real_spec,
    )

    mock_svc = MagicMock()
    mock_svc.suggest = AsyncMock(return_value=[mock_suggestion])

    app.dependency_overrides[get_suggestions_service] = lambda: mock_svc
    app.dependency_overrides[get_tenant_context] = _mock_ctx

    try:
        client = TestClient(app, raise_server_exceptions=True)
        response = client.post(f"/api/v1/ai/datasets/{dataset_id}/suggestions")
        assert response.status_code == 200
        data = response.json()
        assert "suggestions" in data
        assert len(data["suggestions"]) == 1
        assert data["suggestions"][0]["title"] == "Revenue by Region"
    finally:
        app.dependency_overrides.pop(get_suggestions_service, None)
        app.dependency_overrides.pop(get_tenant_context, None)


@pytest.mark.asyncio
async def test_api_suggestions_404_on_unknown_dataset() -> None:
    """POST /ai/datasets/{id}/suggestions with unknown dataset returns 404."""
    from app.ai.insights.suggestions import get_suggestions_service
    from app.main import app
    from app.tenancy.context import get_tenant_context

    dataset_id = uuid.uuid4()
    test_ctx = _make_ctx("api404test")

    async def _mock_ctx() -> TenantContext:
        return test_ctx

    mock_svc = MagicMock()
    mock_svc.suggest = AsyncMock(
        side_effect=HTTPException(status_code=404, detail="Dataset not found")
    )

    app.dependency_overrides[get_suggestions_service] = lambda: mock_svc
    app.dependency_overrides[get_tenant_context] = _mock_ctx

    try:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(f"/api/v1/ai/datasets/{dataset_id}/suggestions")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_suggestions_service, None)
        app.dependency_overrides.pop(get_tenant_context, None)


@pytest.mark.asyncio
async def test_api_suggestions_empty_when_no_suggestions() -> None:
    """POST /ai/datasets/{id}/suggestions with no valid suggestions returns 200 with empty list."""
    from app.ai.insights.suggestions import get_suggestions_service
    from app.main import app
    from app.tenancy.context import get_tenant_context

    dataset_id = uuid.uuid4()
    test_ctx = _make_ctx("apiemptytest")

    async def _mock_ctx() -> TenantContext:
        return test_ctx

    mock_svc = MagicMock()
    mock_svc.suggest = AsyncMock(return_value=[])

    app.dependency_overrides[get_suggestions_service] = lambda: mock_svc
    app.dependency_overrides[get_tenant_context] = _mock_ctx

    try:
        client = TestClient(app, raise_server_exceptions=True)
        response = client.post(f"/api/v1/ai/datasets/{dataset_id}/suggestions")
        assert response.status_code == 200
        data = response.json()
        assert data["suggestions"] == []
        assert data["note"] is not None  # note provided when empty
    finally:
        app.dependency_overrides.pop(get_suggestions_service, None)
        app.dependency_overrides.pop(get_tenant_context, None)
