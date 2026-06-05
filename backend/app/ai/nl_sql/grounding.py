"""Ground stage — build a compact semantic context for prompt injection.

Converts the raw Cube ``/meta`` response (a dict with a ``cubes`` list) into a
compact human-readable description that is safe to inject into the LLM system
prompt.

## Physical table name consistency (FIX 3)

The LLM must write SQL against the PHYSICAL table name (e.g.
``serving_regional_sales``) because that is what the validator allow-list and
the ClickHouse connection use.  The ``semantic_text`` block therefore includes
the governed physical table name (sourced from ``config_tables``) so that the
chain is consistent:

    grounding name  ==  validator allow-list  ==  executed table

Cube's semantic names (e.g. ``regional_sales``) are shown as labels/context for
measures and dimensions, but the LLM is explicitly told the physical table name
to query.

## Allow-list source of truth

The validator's allow-list is sourced exclusively from
``settings.serving_regional_sales_table`` (env: ``SERVING_REGIONAL_SALES_TABLE``).
A compromised or misconfigured Cube instance cannot widen the set of physical
tables that are reachable.  The ``physical_tables`` field on
``GroundingContext`` is populated only from ``config_tables`` and is provided
for reference/logging; the validator never reads it directly.

``sql_table`` annotations from Cube are NOT added to the allow-list or to the
physical table set.  The ``sql`` field on Cube cubes is an arbitrary SQL
fragment and is never treated as a table name.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class GroundingContext:
    """Compact semantic context extracted from the Cube meta response.

    Attributes:
        semantic_text: A human-readable block describing available cubes,
            measures, and dimensions, **including the governed physical table
            name** the LLM must use in its SQL.  Injected verbatim into the
            LLM system prompt.
        physical_tables: The set of lowercase unqualified physical table names
            from the deployment config (``settings.serving_regional_sales_table``).
            Provided for reference and logging only.  The validator allow-list
            is constructed independently in ``NLToSQLService._validate()``
            directly from ``settings.serving_regional_sales_table`` — not from
            this field.
    """

    semantic_text: str
    physical_tables: set[str] = field(default_factory=set)


def build_grounding_context(
    meta: dict[str, Any],
    *,
    config_tables: set[str],
) -> GroundingContext:
    """Build a ``GroundingContext`` from the Cube meta response.

    The semantic text produced here is injected into the LLM system prompt.
    It includes the governed **physical table name(s)** from ``config_tables``
    so the LLM is told the exact table name to write SQL against.  Cube
    semantic names are used only as human-readable labels for measures and
    dimensions.

    Args:
        meta: The parsed JSON body from ``GET /cubejs-api/v1/meta``.
            Expected shape: ``{"cubes": [{"name": str, "measures": [...],
            "dimensions": [...], ...}, ...]}``.
        config_tables: Physical table names from deployment config
            (``settings.serving_regional_sales_table``).  These are the ONLY
            tables that appear in the allow-list and in the semantic text
            shown to the LLM.  Cube annotations (``sql_table``, ``sql``) are
            NOT added here — see module docstring for rationale.

    Returns:
        A ``GroundingContext`` with the compact semantic text and the
        config-derived physical table set.
    """
    cubes: list[dict[str, Any]] = meta.get("cubes", [])
    lines: list[str] = []
    # The physical table set is config-bound only; no Cube annotation widens it.
    physical_tables: set[str] = set(config_tables)

    # Preamble: tell the LLM exactly which physical table(s) it may query.
    if config_tables:
        physical_table_list = ", ".join(sorted(config_tables))
        lines.append(
            f"## Governed physical table(s)\n"
            f"You MUST write your SQL SELECT against one of these physical table(s): "
            f"{physical_table_list}\n"
            f"Do NOT use cube names or semantic layer names as table names in SQL."
        )
        lines.append("")

    for cube in cubes:
        cube_name: str = cube.get("name", "")
        cube_title: str = cube.get("title", cube_name)
        cube_description: str = cube.get("description", "")

        lines.append(f"## Semantic object: {cube_name} ({cube_title})")
        if cube_description:
            lines.append(f"Description: {cube_description}")

        # NOTE: We intentionally do NOT extract sql_table or sql from the Cube
        # meta to add to the allow-list.  The cube.get("sql") value is an
        # arbitrary SQL fragment, not a safe table name.  Only config_tables
        # (from settings.serving_regional_sales_table) are authoritative.

        # Measures — describe as columns the LLM can SELECT from the physical table.
        measures: list[dict[str, Any]] = cube.get("measures", [])
        if measures:
            lines.append("### Measures (columns in the physical table)")
            for m in measures:
                m_name: str = m.get("name", "")
                m_title: str = m.get("title", m_name)
                m_desc: str = m.get("description", "")
                m_type: str = m.get("type", "")
                # Derive column name: strip the "cube_name." prefix if present.
                col_name = m_name.split(".", 1)[-1] if "." in m_name else m_name
                entry = f"  - column: {col_name}  (label: {m_title}, type={m_type})"
                if m_desc:
                    entry += f" — {m_desc}"
                lines.append(entry)

        # Dimensions — same pattern.
        dimensions: list[dict[str, Any]] = cube.get("dimensions", [])
        if dimensions:
            lines.append("### Dimensions (columns in the physical table)")
            for d in dimensions:
                d_name: str = d.get("name", "")
                d_title: str = d.get("title", d_name)
                d_desc: str = d.get("description", "")
                d_type: str = d.get("type", "")
                col_name = d_name.split(".", 1)[-1] if "." in d_name else d_name
                entry = f"  - column: {col_name}  (label: {d_title}, type={d_type})"
                if d_desc:
                    entry += f" — {d_desc}"
                lines.append(entry)

        lines.append("")  # blank separator between cubes

    semantic_text = "\n".join(lines).strip() or "(no governed objects available)"

    logger.debug(
        "build_grounding_context: %d cube(s), physical_tables=%r",
        len(cubes),
        sorted(physical_tables),
    )

    return GroundingContext(
        semantic_text=semantic_text,
        physical_tables=physical_tables,
    )
