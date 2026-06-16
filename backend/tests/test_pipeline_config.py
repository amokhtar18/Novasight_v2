"""Unit tests for the extended PipelineConfig validation (#5/#6/#7).

The field map, keys, partition, structured filter, SCD type and CDC column are all
optional and back-compatible (a bare ``{object}`` still validates as a full
overwrite). These assert the load-mode requirements and the filter-clause rules.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.pipeline import FilterClause, PipelineConfig


def test_minimal_config_is_overwrite() -> None:
    cfg = PipelineConfig(object="orders")
    assert cfg.write_disposition == "overwrite"
    assert cfg.scd_type == "none"
    assert cfg.columns == []


def test_merge_requires_primary_key() -> None:
    with pytest.raises(ValidationError):
        PipelineConfig(object="orders", write_disposition="merge")
    cfg = PipelineConfig(object="orders", write_disposition="merge", primary_key=["id"])
    assert cfg.primary_key == ["id"]


def test_scd1_requires_primary_key() -> None:
    with pytest.raises(ValidationError):
        PipelineConfig(object="orders", scd_type="scd1")
    PipelineConfig(object="orders", scd_type="scd1", primary_key=["id"])


def test_incremental_requires_cdc_column() -> None:
    with pytest.raises(ValidationError):
        PipelineConfig(object="orders", write_disposition="incremental")
    cfg = PipelineConfig(
        object="orders", write_disposition="incremental", cdc_column="updated_at"
    )
    assert cfg.cdc_column == "updated_at"


def test_unique_target_names() -> None:
    with pytest.raises(ValidationError):
        PipelineConfig(
            object="orders",
            columns=[
                {"source_name": "a", "target_name": "x"},
                {"source_name": "b", "target_name": "x"},
            ],
        )


def test_target_type_is_a_closed_set() -> None:
    with pytest.raises(ValidationError):
        PipelineConfig(
            object="orders",
            columns=[{"source_name": "a", "target_name": "x", "target_type": "Blob"}],
        )


def test_filter_clause_value_rules() -> None:
    # A binary operator needs a value; a nullary one must not carry one.
    with pytest.raises(ValidationError):
        FilterClause(column="region", operator="eq")
    with pytest.raises(ValidationError):
        FilterClause(column="region", operator="is_null", value="x")
    # ``in`` takes a list; a scalar is rejected.
    FilterClause(column="region", operator="in", value=["west", "east"])
    with pytest.raises(ValidationError):
        FilterClause(column="region", operator="in", value="west")
    # A strict identifier guards the column (interpolated into SQL).
    with pytest.raises(ValidationError):
        FilterClause(column="region; drop", operator="eq", value="west")
