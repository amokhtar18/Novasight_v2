"""Time-range (date_range) support on SemanticTimeDimension (Slice A)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.semantic import SemanticTimeDimension


def test_relative_token_maps_to_cube_string() -> None:
    td = SemanticTimeDimension(
        dimension="s.created", granularity="month", date_range="last_30_days"
    )
    assert td.cube_date_range == "last 30 days"


def test_absolute_pair_passes_through() -> None:
    td = SemanticTimeDimension(dimension="s.created", date_range=["2024-01-01", "2024-03-31"])
    assert td.cube_date_range == ["2024-01-01", "2024-03-31"]


def test_no_date_range_is_none() -> None:
    td = SemanticTimeDimension(dimension="s.created", granularity="day")
    assert td.cube_date_range is None


def test_unknown_relative_token_rejected() -> None:
    with pytest.raises(ValidationError):
        SemanticTimeDimension(dimension="s.created", date_range="last_decade")


def test_absolute_pair_must_be_two_dates() -> None:
    with pytest.raises(ValidationError, match="exactly two"):
        SemanticTimeDimension(dimension="s.created", date_range=["2024-01-01"])


def test_absolute_pair_must_be_ordered_iso_dates() -> None:
    with pytest.raises(ValidationError):
        SemanticTimeDimension(dimension="s.created", date_range=["2024-03-31", "2024-01-01"])
    with pytest.raises(ValidationError):
        SemanticTimeDimension(dimension="s.created", date_range=["not-a-date", "2024-01-01"])
