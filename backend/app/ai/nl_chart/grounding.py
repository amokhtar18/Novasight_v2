"""Chart grounding stage — build a compact semantic context for prompt injection.

Converts the raw Cube ``/meta`` response into:

1. A human-readable ``semantic_text`` block injected verbatim into the LLM
   system prompt.  The LLM only learns about **governed** metric and dimension
   names from this block — never about raw physical tables.
2. An ``allowed_metrics`` set of fully-qualified measure names that the
   grounding allow-list check uses in Stage 3 to reject any metric the LLM
   invented.
3. An ``allowed_dimensions`` set of fully-qualified dimension names used by the
   same allow-list check for ``encoding.x``.

## Allow-list source of truth

Both sets are derived *exclusively* from the Cube meta response for the
current tenant (scoped by the tenant's JWT at the Cube boundary).  No extra
config tables are added here — the chart path works entirely through the
governed Cube semantic layer, not physical ClickHouse tables.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ChartGroundingContext:
    """Compact semantic context extracted from the Cube meta response.

    Attributes:
        semantic_text: A human-readable block describing available metrics and
            dimensions.  Injected verbatim into the LLM system prompt.
        allowed_metrics: Fully-qualified measure identifiers from the Cube
            meta (e.g. ``{"regional_sales.total_amount"}``).  Used as the
            allow-list to reject ungrounded metric_refs in Stage 3.
        allowed_dimensions: Fully-qualified dimension identifiers from the Cube
            meta (e.g. ``{"regional_sales.region"}``).  Used to reject an
            ``encoding.x`` the LLM invented.
    """

    semantic_text: str
    allowed_metrics: set[str] = field(default_factory=set)
    allowed_dimensions: set[str] = field(default_factory=set)


def build_chart_grounding_context(meta: dict[str, Any]) -> ChartGroundingContext:
    """Build a ``ChartGroundingContext`` from the Cube meta response.

    The semantic text produced here is injected into the LLM system prompt.
    It uses only the governed Cube measure and dimension identifiers — no
    physical table names are surfaced to the LLM.

    Args:
        meta: The parsed JSON body from ``GET /cubejs-api/v1/meta``.
            Expected shape: ``{"cubes": [{"name": str, "measures": [...],
            "dimensions": [...], ...}, ...]}``.

    Returns:
        A ``ChartGroundingContext`` with the compact semantic text and the
        sets of allowed metric and dimension identifiers.
    """
    cubes: list[dict[str, Any]] = meta.get("cubes", [])
    lines: list[str] = []
    allowed_metrics: set[str] = set()
    allowed_dimensions: set[str] = set()

    for cube in cubes:
        cube_name: str = cube.get("name", "")
        cube_title: str = cube.get("title", cube_name)
        cube_description: str = cube.get("description", "")

        lines.append(f"## Semantic object: {cube_name} ({cube_title})")
        if cube_description:
            lines.append(f"Description: {cube_description}")

        # Measures — describe as governed metric names the LLM may put in metric_refs.
        measures: list[dict[str, Any]] = cube.get("measures", [])
        if measures:
            lines.append("### Metrics (use in metric_refs and encoding.series[].field)")
            for m in measures:
                m_name: str = m.get("name", "")
                m_title: str = m.get("title", m_name)
                m_desc: str = m.get("description", "")
                m_type: str = m.get("type", "")
                entry = f"  - metric: {m_name}  (label: {m_title}, type={m_type})"
                if m_desc:
                    entry += f" — {m_desc}"
                lines.append(entry)
                if m_name:
                    allowed_metrics.add(m_name)

        # Dimensions — describe as governed dimension names for encoding.x.
        dimensions: list[dict[str, Any]] = cube.get("dimensions", [])
        if dimensions:
            lines.append("### Dimensions (use in encoding.x)")
            for d in dimensions:
                d_name: str = d.get("name", "")
                d_title: str = d.get("title", d_name)
                d_desc: str = d.get("description", "")
                d_type: str = d.get("type", "")
                entry = f"  - dimension: {d_name}  (label: {d_title}, type={d_type})"
                if d_desc:
                    entry += f" — {d_desc}"
                lines.append(entry)
                if d_name:
                    allowed_dimensions.add(d_name)

        lines.append("")  # blank separator between cubes

    semantic_text = "\n".join(lines).strip() or "(no governed objects available)"

    logger.debug(
        "build_chart_grounding_context: %d cube(s) metrics=%r dimensions=%r",
        len(cubes),
        sorted(allowed_metrics),
        sorted(allowed_dimensions),
    )

    return ChartGroundingContext(
        semantic_text=semantic_text,
        allowed_metrics=allowed_metrics,
        allowed_dimensions=allowed_dimensions,
    )
