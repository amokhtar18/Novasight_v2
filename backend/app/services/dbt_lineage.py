"""dbt lineage: derive a dependency DAG from stored model SQL (#5).

Parses ``{{ ref('name') }}`` and ``{{ source('src', 'table') }}`` references out of
each model's SQL and builds a directed graph (upstream → downstream). Self-contained
and in-app — no dbt manifest or external catalog needed (that was the chosen scope).

Everything here is a pure function over the stored definitions, so it is unit-tested
directly without a database. Node ids are namespaced (``model:``/``source:``/``external:``)
so a model and a same-named source can't collide.
"""
from __future__ import annotations

import re
from collections.abc import Sequence

from pydantic import BaseModel, Field

from app.models.dbt_model import DbtModel

# ``ref('model_name')`` — single identifier argument (dbt model names are identifiers).
_REF_RE = re.compile(r"ref\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\s*\)")
# ``source('source_name', 'table_name')`` — two string arguments.
_SOURCE_RE = re.compile(r"source\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)")


class LineageNode(BaseModel):
    """One node in the lineage graph."""

    id: str = Field(description="Namespaced node id, e.g. 'model:mart_orders'.")
    label: str = Field(description="Display name.")
    kind: str = Field(description="'model' | 'source' | 'external'.")
    layer: str | None = Field(default=None, description="dbt layer for model nodes.")


class LineageEdge(BaseModel):
    """A directed dependency: ``source`` (upstream) feeds ``target`` (downstream)."""

    source: str
    target: str


class LineageGraph(BaseModel):
    """The whole dbt dependency DAG for a tenant."""

    nodes: list[LineageNode] = Field(default_factory=list)
    edges: list[LineageEdge] = Field(default_factory=list)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for i in items:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def parse_dependencies(sql: str | None) -> tuple[list[str], list[str]]:
    """Return ``(ref_names, source_keys)`` parsed from one model's SQL.

    ``source_keys`` are ``"<source>.<table>"``. Both lists are de-duplicated and keep
    first-seen order. ``None``/empty SQL yields two empty lists.
    """
    text = sql or ""
    refs = [m.group(1) for m in _REF_RE.finditer(text)]
    sources = [f"{m.group(1)}.{m.group(2)}" for m in _SOURCE_RE.finditer(text)]
    return _dedupe(refs), _dedupe(sources)


def build_lineage(models: Sequence[DbtModel]) -> LineageGraph:
    """Build the dependency DAG for a tenant's dbt models.

    Each model is a node; a ``ref`` to a known model adds an edge from that model, a
    ``ref`` to an unknown name adds an ``external`` node + edge, and a ``source(...)``
    adds a ``source`` node + edge. Duplicate edges are collapsed.
    """
    nodes: dict[str, LineageNode] = {}
    edges: list[LineageEdge] = []
    model_names = {m.name for m in models}

    for m in models:
        node_id = f"model:{m.name}"
        nodes[node_id] = LineageNode(id=node_id, label=m.name, kind="model", layer=m.layer)

    for m in models:
        target = f"model:{m.name}"
        refs, sources = parse_dependencies(m.sql)
        for ref in refs:
            if ref in model_names:
                source_id = f"model:{ref}"
            else:
                source_id = f"external:{ref}"
                nodes.setdefault(
                    source_id, LineageNode(id=source_id, label=ref, kind="external")
                )
            edges.append(LineageEdge(source=source_id, target=target))
        for src in sources:
            source_id = f"source:{src}"
            nodes.setdefault(source_id, LineageNode(id=source_id, label=src, kind="source"))
            edges.append(LineageEdge(source=source_id, target=target))

    seen: set[tuple[str, str]] = set()
    unique_edges: list[LineageEdge] = []
    for edge in edges:
        key = (edge.source, edge.target)
        if key not in seen:
            seen.add(key)
            unique_edges.append(edge)

    return LineageGraph(nodes=list(nodes.values()), edges=unique_edges)
