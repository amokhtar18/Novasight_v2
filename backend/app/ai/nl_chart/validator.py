"""Validate stage — parse and guardrail AI-generated chart specs before use.

This module is the security-critical chokepoint between LLM output and the
chart resolver.  It is called BEFORE any data query reaches the semantic layer.

## Guardrails enforced (in order)

1. **UNSATISFIABLE sentinel** — if the LLM returned ``UNSATISFIABLE`` the
   request cannot be satisfied from the governed objects; raise immediately.
2. **JSON parse** — the LLM output must be valid JSON; anything else is rejected.
3. **Strict schema validation** — the parsed JSON is validated against
   ``ChartSpec`` in strict (no-extra-fields) mode, enforcing all existing
   ChartSpec invariants:
   - ``type`` in {bar, line, area, pie, table};
   - ``encoding.series`` has ≥1 entry;
   - ``encoding.x`` is required for non-table charts;
   - ``FieldName`` pattern is satisfied by all fields/metric refs.
4. **AI-path gate** — the validated spec MUST use ``metric_refs`` (the AI path).
   A spec with an inline ``query.query`` is rejected to keep one grounded path.
5. **Grounding allow-list** — every ``metric_refs`` entry and every
   ``encoding.series[].field`` must exist in the tenant's Cube meta
   (``allowed_metrics``).  Every ``encoding.x`` (when present) must exist in
   ``allowed_dimensions``.  Any metric or dimension the LLM invented that is not
   in the governed meta is rejected here — this is the hard tenant-safety gate.

On ANY guardrail violation a ``ChartValidationError`` is raised.  The caller
(``NLToChartService``) must NEVER resolve data when validation fails.

## Strict-mode parsing without mutating the shared schema

``ChartSpec`` is the shared backend↔frontend contract and must not be changed.
Strict-field enforcement (reject unknown/extra JSON fields) is applied here by
building a temporary ``model_config``-overriding subclass at validation time,
following the Pydantic v2 documented pattern.  The original ``ChartSpec`` class
and its round-trip behaviour are untouched.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ConfigDict, Field, ValidationError

from app.schemas.chart import (
    ChartEncoding,
    ChartOptions,
    ChartQuery,
    ChartSpec,
    SeriesEncoding,
)

logger = logging.getLogger(__name__)

# Sentinel the LLM emits when it cannot answer from the semantic layer.
_UNSATISFIABLE = "UNSATISFIABLE"


class ChartValidationError(Exception):
    """Raised when the generated chart spec fails any guardrail.

    The ``reason`` attribute is safe to return to the caller (no raw LLM output,
    no internal details).  Do not include the raw JSON in the message — it may
    contain injected content.

    Attributes:
        reason: A short human-readable description of the guardrail that fired.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# ---------------------------------------------------------------------------
# Strict-mode ChartSpec subclasses (never exported — internal to this module)
# ---------------------------------------------------------------------------
# We build strict-extras sub-models here so the shared ChartSpec contract is
# untouched.  Pydantic v2: set ``model_config = ConfigDict(extra="forbid")``
# on each sub-model used in the strict parse.


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
    """ChartSpec with ``extra='forbid'`` — used ONLY for strict AI-output parsing.

    This subclass is NEVER exposed outside this module.  It shares all field
    definitions and validators from the canonical ``ChartSpec``; the only
    addition is ``extra="forbid"`` so that JSON fields the LLM hallucinated
    (and that don't belong in the schema) are rejected rather than silently
    dropped.

    The canonical ``ChartSpec`` is left untouched so the frontend round-trip
    contract is unaffected.
    """

    model_config = ConfigDict(extra="forbid")

    query: _StrictChartQuery
    encoding: _StrictChartEncoding
    options: _StrictChartOptions = _StrictChartOptions()

    # The parent ChartSpec's `@model_validator` (_require_x_for_axis_charts) is
    # inherited and DOES run on this subclass in Pydantic v2 — no re-declaration
    # needed. Re-declaring it would risk silent divergence from the base contract.


# ---------------------------------------------------------------------------
# Public validation entry point
# ---------------------------------------------------------------------------


def validate_chart_spec(
    raw_output: str,
    *,
    allowed_metrics: set[str],
    allowed_dimensions: set[str],
) -> ChartSpec:
    """Parse, validate, and grounding-check an AI-generated chart spec.

    This function is the security chokepoint — it must be called on EVERY
    LLM-generated chart spec string before any data resolution occurs.  It is
    intentionally strict: on any doubt the spec is rejected.

    Args:
        raw_output: The raw string returned by the LLM.
        allowed_metrics: Fully-qualified Cube measure names for this tenant
            (from ``ChartGroundingContext.allowed_metrics``).
        allowed_dimensions: Fully-qualified Cube dimension names for this
            tenant (from ``ChartGroundingContext.allowed_dimensions``).

    Returns:
        A validated ``ChartSpec`` (canonical, not the strict sub-class) when
        all guardrails pass.

    Raises:
        ChartValidationError: If any guardrail fires.
    """
    stripped = raw_output.strip()

    # ------------------------------------------------------------------
    # 1. UNSATISFIABLE sentinel
    # ------------------------------------------------------------------
    if stripped.upper() == _UNSATISFIABLE:
        raise ChartValidationError(
            "The chart request cannot be answered from the available governed "
            "objects. Please rephrase your request or use the manual chart builder."
        )

    # ------------------------------------------------------------------
    # 2. JSON parse
    # ------------------------------------------------------------------
    try:
        raw_dict: Any = json.loads(stripped)
    except json.JSONDecodeError as exc:
        logger.warning("Chart spec JSON parse error: %s", exc)
        raise ChartValidationError(
            "The generated chart spec is not valid JSON. "
            "Please rephrase your request."
        ) from exc

    if not isinstance(raw_dict, dict):
        raise ChartValidationError(
            "The generated chart spec must be a JSON object. "
            "Please rephrase your request."
        )

    # ------------------------------------------------------------------
    # 3. Strict schema validation (extra fields forbidden, invariants enforced)
    # ------------------------------------------------------------------
    try:
        strict_spec = _StrictChartSpec.model_validate(raw_dict)
    except ValidationError as exc:
        # Extract user-safe summary: list field paths and short messages.
        errors = exc.errors(include_url=False)
        summary = "; ".join(
            f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}"
            for e in errors[:3]  # cap at 3 to avoid verbose leakage
        )
        logger.warning("Chart spec schema validation failed: %s", summary)
        raise ChartValidationError(
            f"The generated chart spec does not match the required schema: {summary}. "
            "Please rephrase your request or use the manual chart builder."
        ) from exc

    # ------------------------------------------------------------------
    # 4. AI-path gate: must use metric_refs; inline query is disallowed
    # ------------------------------------------------------------------
    if strict_spec.query.query is not None:
        raise ChartValidationError(
            "The AI chart path must use metric_refs, not an inline dataset query. "
            "Please rephrase your request."
        )

    # A dataset_id is the other half of the inline-dataset path. Reject it too:
    # even though _resolve only ever queries metric_refs, an LLM-emitted dataset_id
    # would otherwise survive into the returned spec, pointing at a dataset record
    # (potentially another tenant's). The AI path is metric_refs ONLY.
    if strict_spec.query.dataset_id is not None:
        raise ChartValidationError(
            "The AI chart path must use metric_refs only; a dataset_id is not "
            "permitted. Please rephrase your request."
        )

    if not strict_spec.query.metric_refs:
        raise ChartValidationError(
            "The generated chart spec has no metric_refs. "
            "Please rephrase your request to reference a specific metric."
        )

    # ------------------------------------------------------------------
    # 5. Grounding allow-list: every metric and dimension must be governed
    # ------------------------------------------------------------------
    # Normalise to lowercase for case-insensitive comparison.
    allowed_metrics_lower = {m.lower() for m in allowed_metrics}
    allowed_dimensions_lower = {d.lower() for d in allowed_dimensions}

    for ref in strict_spec.query.metric_refs:
        if ref.lower() not in allowed_metrics_lower:
            logger.warning(
                "Chart spec grounding rejection: metric_ref=%r not in governed metrics=%r",
                ref,
                sorted(allowed_metrics),
            )
            raise ChartValidationError(
                f"The generated chart references metric '{ref}' which is not in the "
                "governed semantic layer for this tenant. "
                "Please rephrase using only the available metrics."
            )

    # Every series field must be both (a) a governed metric and (b) listed in
    # metric_refs. Without (b), the field is never sent to Cube as a measure, so the
    # resolved data has no column for it — the renderer would silently plot nulls as
    # zeros, producing a misleading chart with no error. Enforce the alignment.
    metric_refs_lower = {ref.lower() for ref in strict_spec.query.metric_refs}
    for series in strict_spec.encoding.series:
        field_lower = series.field.lower()
        if field_lower not in allowed_metrics_lower:
            logger.warning(
                "Chart spec grounding rejection: series.field=%r not in governed metrics=%r",
                series.field,
                sorted(allowed_metrics),
            )
            raise ChartValidationError(
                f"The generated chart references series field '{series.field}' which is "
                "not in the governed semantic layer for this tenant. "
                "Please rephrase using only the available metrics."
            )
        if field_lower not in metric_refs_lower:
            logger.warning(
                "Chart spec rejection: series.field=%r not listed in metric_refs=%r",
                series.field,
                strict_spec.query.metric_refs,
            )
            raise ChartValidationError(
                f"The generated chart series field '{series.field}' is not listed in "
                "metric_refs, so it would have no data. Please rephrase your request."
            )

    x_field = strict_spec.encoding.x
    if x_field is not None and x_field.lower() not in allowed_dimensions_lower:
        logger.warning(
            "Chart spec grounding rejection: encoding.x=%r not in governed dims=%r",
            x_field,
            sorted(allowed_dimensions),
        )
        raise ChartValidationError(
            f"The generated chart uses dimension '{x_field}' which is "
            "not in the governed semantic layer for this tenant. "
            "Please rephrase using only the available dimensions."
        )

    logger.info(
        "Chart spec validation passed: type=%r metric_refs=%r encoding_x=%r",
        strict_spec.type,
        strict_spec.query.metric_refs,
        strict_spec.encoding.x,
    )

    # Return a canonical ChartSpec (not the strict subclass).
    return ChartSpec.model_validate(strict_spec.model_dump())
