"""Validate stage for AI-generated dataset suggestions — sub-feature (b).

Each suggestion from the LLM is a {title, rationale, spec} JSON object.
This module validates each one and silently drops (rather than hard-rejects)
invalid entries so the caller gets back as many valid suggestions as survived.

## Guardrails enforced per suggestion

1. **JSON structure**: must have ``title``, ``rationale``, and ``spec`` keys.
2. **Schema validation**: ``spec`` must validate against ``ChartSpec`` in strict
   (no-extra-fields) mode, exactly like the NL→Chart path.
3. **Column allow-list** (the core safety gate for sub-feature b):
   - Every ``query.query.dimensions`` entry must be in the profiled column set.
   - Every ``query.query.metrics[].column`` must be in the profiled column set
     (or may be None for ``count(*)``, which is always allowed).
   - Every ``encoding.series[].field`` must match a ``metrics[].alias``.
   - ``encoding.x`` (when not None) must be in the profiled column set.
   The LLM must not invent columns.  Any column name not present in the
   dataset profile is rejected at this gate.
4. **Inline-dataset path gate**: spec MUST use ``query.dataset_id`` + ``query.query``
   (the inline dataset path), NOT ``metric_refs`` (which is the semantic-layer
   path and has no meaning for raw dataset columns).

Invalid suggestions are logged and dropped; the caller gets an empty list
(with a note) if none survive — it never 500s.
"""
from __future__ import annotations

import logging

from pydantic import ConfigDict, Field, ValidationError

from app.schemas.chart import (
    ChartEncoding,
    ChartOptions,
    ChartQuery,
    ChartSpec,
    SeriesEncoding,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Strict-mode ChartSpec sub-models (mirror of nl_chart/validator.py pattern)
# ---------------------------------------------------------------------------


class _StrictSeriesEncoding(SeriesEncoding):
    model_config = ConfigDict(extra="forbid")


class _StrictChartEncoding(ChartEncoding):
    model_config = ConfigDict(extra="forbid")
    series: list[_StrictSeriesEncoding] = Field(min_length=1)  # type: ignore[assignment]


class _StrictChartQuery(ChartQuery):
    model_config = ConfigDict(extra="forbid")


class _StrictChartOptions(ChartOptions):
    model_config = ConfigDict(extra="forbid")


class _StrictChartSpec(ChartSpec):
    """ChartSpec with ``extra='forbid'`` — used only for AI suggestion validation."""

    model_config = ConfigDict(extra="forbid")
    query: _StrictChartQuery
    encoding: _StrictChartEncoding
    options: _StrictChartOptions = _StrictChartOptions()


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class ValidatedSuggestion:
    """A single validated chart suggestion.

    Attributes:
        title: Short human-readable title.
        rationale: One-sentence explanation of the suggestion's value.
        spec: Fully validated ``ChartSpec`` using the inline dataset path.
    """

    def __init__(self, title: str, rationale: str, spec: ChartSpec) -> None:
        self.title = title
        self.rationale = rationale
        self.spec = spec


# ---------------------------------------------------------------------------
# Validation logic
# ---------------------------------------------------------------------------


def _validate_one_suggestion(
    raw: object,
    *,
    allowed_columns: set[str],
    dataset_id_str: str,
) -> ValidatedSuggestion | None:
    """Validate a single raw suggestion dict.

    Returns a ``ValidatedSuggestion`` on success, ``None`` on any failure
    (with a debug log explaining the reason).
    """
    # Guard 1: must be a dict
    if not isinstance(raw, dict):
        logger.debug("Suggestion dropped: not a dict, got %r", type(raw).__name__)
        return None

    title = raw.get("title")
    rationale = raw.get("rationale")
    spec_dict = raw.get("spec")

    if not isinstance(title, str) or not title.strip():
        logger.debug("Suggestion dropped: missing or empty 'title'")
        return None

    if not isinstance(rationale, str) or not rationale.strip():
        logger.debug("Suggestion dropped: missing or empty 'rationale'")
        return None

    if not isinstance(spec_dict, dict):
        logger.debug("Suggestion dropped: 'spec' is not a dict")
        return None

    # Guard 2: strict schema validation
    try:
        strict_spec = _StrictChartSpec.model_validate(spec_dict)
    except ValidationError as exc:
        errors = exc.errors(include_url=False)
        summary = "; ".join(
            f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}"
            for e in errors[:3]
        )
        logger.debug("Suggestion dropped: schema validation failed: %s", summary)
        return None

    # Guard 3: must use inline dataset path (dataset_id + query), NOT metric_refs
    if strict_spec.query.metric_refs:
        logger.debug(
            "Suggestion dropped: spec uses metric_refs (semantic layer path); "
            "suggestions must use the inline dataset path"
        )
        return None

    if strict_spec.query.query is None:
        logger.debug("Suggestion dropped: spec has no inline query.query")
        return None

    # Guard 3b: dataset_id must match the profiled dataset (not LLM-invented)
    spec_dataset_id = strict_spec.query.dataset_id
    if spec_dataset_id is None or str(spec_dataset_id) != dataset_id_str:
        logger.debug(
            "Suggestion dropped: spec.query.dataset_id %r does not match "
            "dataset %r",
            spec_dataset_id,
            dataset_id_str,
        )
        return None

    # Guard 4: column allow-list
    inline_query = strict_spec.query.query

    # Dimensions must all be in the profiled columns
    allowed_lower = {c.lower() for c in allowed_columns}
    for dim in inline_query.dimensions:
        if dim.lower() not in allowed_lower:
            logger.debug(
                "Suggestion dropped: dimension %r not in dataset columns %r",
                dim,
                sorted(allowed_columns),
            )
            return None

    # Metric columns (if not None, i.e. not count(*)) must be in profiled columns
    alias_set: set[str] = set()
    for metric in inline_query.metrics:
        if metric.column is not None and metric.column.lower() not in allowed_lower:
            logger.debug(
                "Suggestion dropped: metric column %r not in dataset columns %r",
                metric.column,
                sorted(allowed_columns),
            )
            return None
        alias = metric.alias or f"{metric.function}_0"
        alias_set.add(alias.lower())

    # encoding.x must be in profiled columns (or None for table charts)
    if (
        strict_spec.encoding.x is not None
        and strict_spec.encoding.x.lower() not in allowed_lower
    ):
        logger.debug(
            "Suggestion dropped: encoding.x %r not in dataset columns %r",
            strict_spec.encoding.x,
            sorted(allowed_columns),
        )
        return None

    # encoding.series[].field must match a metric alias
    for series in strict_spec.encoding.series:
        if series.field.lower() not in alias_set:
            logger.debug(
                "Suggestion dropped: series.field %r does not match any metric alias %r",
                series.field,
                sorted(alias_set),
            )
            return None

    # All guards passed — return canonical ChartSpec
    canonical_spec = ChartSpec.model_validate(strict_spec.model_dump())
    return ValidatedSuggestion(
        title=title.strip(),
        rationale=rationale.strip(),
        spec=canonical_spec,
    )


def validate_suggestions(
    raw_suggestions: list[object],
    *,
    allowed_columns: set[str],
    dataset_id_str: str,
) -> list[ValidatedSuggestion]:
    """Validate a list of raw suggestion dicts from the LLM.

    Silently drops invalid suggestions.  Returns an empty list if none
    survive validation — the caller should surface a user-friendly note
    rather than 500-ing.

    Args:
        raw_suggestions: The parsed list from the LLM's JSON output.
        allowed_columns: Column names present in the dataset profile
            (the allow-list for column references).
        dataset_id_str: The string UUID of the dataset being profiled.
            All ``spec.query.dataset_id`` values must match this.

    Returns:
        A list of ``ValidatedSuggestion`` objects (possibly empty).
    """
    valid: list[ValidatedSuggestion] = []
    for i, raw in enumerate(raw_suggestions):
        result = _validate_one_suggestion(
            raw,
            allowed_columns=allowed_columns,
            dataset_id_str=dataset_id_str,
        )
        if result is not None:
            valid.append(result)
        else:
            logger.info(
                "validate_suggestions: suggestion[%d] dropped (see debug logs for reason)",
                i,
            )
    logger.info(
        "validate_suggestions: %d/%d suggestions passed validation",
        len(valid),
        len(raw_suggestions),
    )
    return valid
