"""Contract tests for the shared chart-spec (Task 3.1).

The acceptance criterion is "a spec round-trips backend↔frontend". The crossing
point between the two languages is a single canonical JSON fixture,
``docs/examples/chart-spec.example.json``. Here we prove the *backend* half:

* the fixture parses into a ``ChartSpec`` and serialises back to byte-for-value
  identical JSON (no field dropped, renamed, or defaulted away), and
* the schema's invariants (data source required, x required for axis charts,
  at least one series) actually hold.

The frontend half — that the *same* fixture is assignable to the TS ``ChartSpec``
and drives the renderer — lives in ``frontend/src/test/chartSpec.test.ts``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.chart import ChartSpec

# Repo root is three levels up from this file: tests/ -> backend/ -> repo root.
FIXTURE = Path(__file__).resolve().parents[2] / "docs" / "examples" / "chart-spec.example.json"


def _fixture_dict() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_canonical_fixture_round_trips() -> None:
    """fixture JSON → ChartSpec → JSON is value-identical to the fixture."""
    raw = _fixture_dict()
    spec = ChartSpec.model_validate(raw)
    dumped = spec.model_dump(mode="json")
    assert dumped == raw, "round-trip changed the spec; backend and fixture have drifted"


def test_fixture_uses_current_version() -> None:
    spec = ChartSpec.model_validate(_fixture_dict())
    assert spec.version == "2"


def test_chart_query_requires_a_source() -> None:
    """A ChartQuery with neither inline query nor metric_refs is rejected."""
    with pytest.raises(ValidationError, match="needs an inline 'query'"):
        ChartSpec.model_validate(
            {
                "type": "bar",
                "query": {"dataset_id": None, "query": None, "metric_refs": []},
                "encoding": {"x": "month", "series": [{"field": "sales"}]},
            }
        )


def test_metric_refs_alone_is_a_valid_source() -> None:
    """The semantic-layer path (metric_refs, no inline query) is accepted."""
    spec = ChartSpec.model_validate(
        {
            "type": "line",
            "query": {"metric_refs": ["orders.revenue"]},
            "encoding": {"x": "order_month", "series": [{"field": "orders.revenue"}]},
        }
    )
    assert spec.query.metric_refs == ["orders.revenue"]
    assert spec.query.query is None


def test_axis_chart_requires_x() -> None:
    with pytest.raises(ValidationError, match=r"requires encoding\.x"):
        ChartSpec.model_validate(
            {
                "type": "bar",
                "query": {"metric_refs": ["m"]},
                "encoding": {"series": [{"field": "sales"}]},
            }
        )


def test_table_may_omit_x() -> None:
    """A table presents columns and so does not need a category axis."""
    spec = ChartSpec.model_validate(
        {
            "type": "table",
            "query": {"metric_refs": ["m"]},
            "encoding": {"series": [{"field": "sales"}, {"field": "returns"}]},
        }
    )
    assert spec.encoding.x is None


def test_number_may_omit_x() -> None:
    """A number (KPI) tile is a single value and so does not need a category axis."""
    spec = ChartSpec.model_validate(
        {
            "type": "number",
            "query": {"metric_refs": ["orders.revenue"]},
            "encoding": {"series": [{"field": "orders.revenue"}]},
        }
    )
    assert spec.type == "number"
    assert spec.encoding.x is None


def test_scatter_requires_x() -> None:
    """Scatter plots x vs y, so (unlike table/number) it still needs encoding.x."""
    with pytest.raises(ValidationError, match=r"requires encoding\.x"):
        ChartSpec.model_validate(
            {
                "type": "scatter",
                "query": {"metric_refs": ["m"]},
                "encoding": {"series": [{"field": "rating"}]},
            }
        )


def test_scatter_round_trips_with_x() -> None:
    spec = ChartSpec.model_validate(
        {
            "type": "scatter",
            "query": {"metric_refs": ["orders.price", "orders.rating"]},
            "encoding": {"x": "orders.price", "series": [{"field": "orders.rating"}]},
        }
    )
    assert spec.type == "scatter"
    assert spec.encoding.x == "orders.price"


def test_at_least_one_series_required() -> None:
    with pytest.raises(ValidationError):
        ChartSpec.model_validate(
            {
                "type": "bar",
                "query": {"metric_refs": ["m"]},
                "encoding": {"x": "month", "series": []},
            }
        )


def test_field_name_rejects_injection() -> None:
    """Encoding fields are pattern-bounded — no spaces / punctuation smuggling."""
    with pytest.raises(ValidationError):
        ChartSpec.model_validate(
            {
                "type": "bar",
                "query": {"metric_refs": ["m"]},
                "encoding": {"x": "month; drop table", "series": [{"field": "sales"}]},
            }
        )


# --- v2 chart types + formatting options (#8) -------------------------------

@pytest.mark.parametrize("chart_type", ["hbar", "combo", "donut", "funnel", "treemap", "radar"])
def test_new_axis_chart_types_accept_x_and_series(chart_type: str) -> None:
    spec = ChartSpec.model_validate(
        {
            "type": chart_type,
            "query": {"metric_refs": ["sales.total"]},
            "encoding": {"x": "sales.region", "series": [{"field": "sales.total"}]},
        }
    )
    assert spec.type == chart_type


def test_gauge_may_omit_x() -> None:
    # gauge is a single-value dial — like number/table it needs no category axis.
    spec = ChartSpec.model_validate(
        {
            "type": "gauge",
            "query": {"metric_refs": ["sales.total"]},
            "encoding": {"series": [{"field": "sales.total"}]},
        }
    )
    assert spec.type == "gauge"
    assert spec.encoding.x is None


def test_v2_version_is_current() -> None:
    from app.schemas.chart import CHART_SPEC_VERSION
    assert CHART_SPEC_VERSION == "2"


def test_v2_shared_chrome_options() -> None:
    spec = ChartSpec.model_validate(
        {
            "type": "bar",
            "query": {"metric_refs": ["sales.total"]},
            "encoding": {"x": "sales.region", "series": [{"field": "sales.total"}]},
            "options": {
                "title": "Sales",
                "color_scheme": "vibrant",
                "legend": {"show": True, "position": "bottom", "type": "plain", "sort": "desc"},
                "number_format": {"style": "currency", "currency": "$", "prefix": "≈", "suffix": " net"},
                "date_format": "%Y-%m",
                "labels": {"show": True, "threshold": 5, "template": "{value}"},
                "tooltip": {"mode": "rich", "show_total": True, "show_percentage": True},
            },
        }
    )
    assert spec.version == "2"
    assert spec.options.legend.position == "bottom"
    assert spec.options.legend.type == "plain"
    assert spec.options.number_format.prefix == "≈"
    assert spec.options.tooltip.mode == "rich"
    assert spec.options.labels.threshold == 5


def test_v2_options_default_empty() -> None:
    spec = ChartSpec.model_validate(
        {
            "type": "bar",
            "query": {"metric_refs": ["sales.total"]},
            "encoding": {"x": "sales.region", "series": [{"field": "sales.total"}]},
        }
    )
    assert spec.options.legend.show is True
    assert spec.options.tooltip.mode == "axis"
    assert spec.options.labels.show is False
    assert spec.options.type_options is None


def test_v2_rejects_legacy_flat_options() -> None:
    # Legacy flat fields are gone; Pydantic ignores unknown keys by default, so assert
    # the model has no such attribute rather than expecting an error.
    spec = ChartSpec.model_validate(
        {
            "type": "bar",
            "query": {"metric_refs": ["sales.total"]},
            "encoding": {"x": "sales.region", "series": [{"field": "sales.total"}]},
            "options": {"stacked": True},
        }
    )
    assert not hasattr(spec.options, "stacked")


def test_invalid_palette_colour_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ChartSpec.model_validate(
            {
                "type": "bar",
                "query": {"metric_refs": ["sales.total"]},
                "encoding": {"x": "sales.region", "series": [{"field": "sales.total"}]},
                "options": {"palette": ["not-a-color"]},
            }
        )


def test_chart_query_carries_filters_order_limit() -> None:
    spec = ChartSpec.model_validate(
        {
            "type": "bar",
            "query": {
                "metric_refs": ["sales.total"],
                "dimensions": ["sales.region"],
                "filters": [
                    {"member": "sales.region", "operator": "equals", "values": ["west"]}
                ],
                "order": {"sales.total": "desc"},
                "limit": 25,
            },
            "encoding": {"x": "sales.region", "series": [{"field": "sales.total"}]},
        }
    )
    assert spec.query.filters[0].member == "sales.region"
    assert spec.query.order == {"sales.total": "desc"}
    assert spec.query.limit == 25


def test_chart_query_defaults_are_empty() -> None:
    spec = ChartSpec.model_validate(
        {
            "type": "bar",
            "query": {"metric_refs": ["sales.total"]},
            "encoding": {"x": "sales.region", "series": [{"field": "sales.total"}]},
        }
    )
    assert spec.query.filters == []
    assert spec.query.order == {}
    assert spec.query.limit is None


def test_chart_query_time_dimension_date_range_round_trips() -> None:
    spec = ChartSpec.model_validate(
        {
            "type": "line",
            "query": {
                "metric_refs": ["sales.total"],
                "time_dimensions": [
                    {
                        "dimension": "sales.created",
                        "granularity": "month",
                        "date_range": "last_90_days",
                    }
                ],
            },
            "encoding": {"x": "sales.created.month", "series": [{"field": "sales.total"}]},
        }
    )
    assert spec.query.time_dimensions[0].cube_date_range == "last 90 days"
