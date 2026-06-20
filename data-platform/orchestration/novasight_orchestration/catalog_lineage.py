"""Cross-system lineage into OpenMetadata (Phase 5.3, lineage stage).

dlt and Cube do not emit OpenMetadata lineage, but NovaSight already knows every
edge from its own registry: a ``pipelines`` row maps a *source object* → a *landing
table* (in both the Iceberg namespace and the ClickHouse database), and a
``semantic_models`` row maps a *Cube cube* → its *ClickHouse base table*. This module
turns those rows into OpenMetadata lineage edges so the catalog shows the full
``source → Iceberg → ClickHouse → Cube`` chain on top of the per-table metadata the
ingestion stages register and the model→model lineage dbt provides.

## Design — pure core, injected emission (mirrors ``catalog._run_workflow``)

* The **edge builders** are pure: from registry rows + the tenant ``CatalogScope`` they
  produce ``LineageEdge`` values addressed by logical coordinates (``TableRef``). No
  source credentials are needed — this is metadata only (golden rule 2: every ref is
  scoped to the tenant's own namespace / database).
* The **emitter** (``_emit_lineage``) is injected and lazily imports the optional
  OpenMetadata SDK, so the code location and its unit tests never require it. Turning a
  ``TableRef`` into a fully-qualified name + entity and POSTing ``AddLineageRequest`` is
  the live-verified integration boundary, exactly like the ingestion-workflow runner.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol

from .catalog import CatalogScope, run_om_runner
from .registry import CatalogPipelineRow, CatalogSemanticRow
from .settings import OrchestrationSettings

STAGE_LINEAGE = "cross_system_lineage"

# Every OpenMetadata database-connector entity is registered under a container
# "database" beneath its service; for our single-connection services this is the
# conventional ``default``. Keeping every ref a 4-part ``service.database.schema.table``
# FQN means source, Iceberg, ClickHouse, and Cube are all uniform table↔table edges.
_OM_DB_CONTAINER = "default"


@dataclass(frozen=True)
class TableRef:
    """Logical coordinates of one OpenMetadata table entity (a lineage endpoint)."""

    service: str
    database: str   # OM database container (``default`` for our services)
    schema: str     # OM databaseSchema — the tenant's namespace / DB / source schema
    table: str

    @property
    def fqn(self) -> str:
        """The OpenMetadata fully-qualified name ``service.database.schema.table``."""
        return f"{self.service}.{self.database}.{self.schema}.{self.table}"


@dataclass(frozen=True)
class LineageEdge:
    """A directed lineage edge ``from_ref`` → ``to_ref`` (upstream → downstream)."""

    from_ref: TableRef
    to_ref: TableRef


@dataclass(frozen=True)
class LineageResult:
    """Outcome of the lineage stage."""

    edge_count: int
    stage: str = STAGE_LINEAGE


class LineageEmitter(Protocol):
    """Posts a batch of lineage edges to OpenMetadata."""

    def __call__(self, edges: list[LineageEdge], settings: OrchestrationSettings) -> None: ...


# --- ref builders (pure, tenant-scoped) --------------------------------------


def clickhouse_ref(settings: OrchestrationSettings, scope: CatalogScope, table: str) -> TableRef:
    """A ClickHouse table in the tenant's database, under the ClickHouse OM service."""
    return TableRef(
        service=settings.catalog.service_name,
        database=_OM_DB_CONTAINER,
        schema=scope.clickhouse_db,
        table=table,
    )


def iceberg_ref(settings: OrchestrationSettings, scope: CatalogScope, table: str) -> TableRef:
    """An Iceberg landing table in the tenant's namespace, under the Iceberg OM service."""
    return TableRef(
        service=settings.catalog.iceberg_service_name,
        database=_OM_DB_CONTAINER,
        schema=scope.iceberg_namespace or scope.clickhouse_db,
        table=table,
    )


def source_ref(settings: OrchestrationSettings, pipeline: CatalogPipelineRow) -> TableRef:
    """The upstream source object, under the shared sources OM service.

    Files have no schema, so the source connection's name stands in — keeping the ref
    deterministic and the source side of the lineage legible per connection.
    """
    return TableRef(
        service=settings.catalog.source_service_name,
        database=_OM_DB_CONTAINER,
        schema=pipeline.source_schema or pipeline.source_name,
        table=pipeline.source_object or pipeline.target_table,
    )


def cube_ref(settings: OrchestrationSettings, scope: CatalogScope, cube: str) -> TableRef:
    """A Cube cube as a logical table in the tenant schema, under the semantic OM service."""
    return TableRef(
        service=settings.catalog.semantic_service_name,
        database=_OM_DB_CONTAINER,
        schema=scope.clickhouse_db,
        table=cube,
    )


# --- edge builders (pure) ----------------------------------------------------


def build_pipeline_edges(
    settings: OrchestrationSettings,
    scope: CatalogScope,
    pipelines: list[CatalogPipelineRow],
) -> list[LineageEdge]:
    """``source → Iceberg → ClickHouse`` edges for each of the tenant's pipelines.

    When the tenant has an Iceberg namespace the lake hop is included
    (source → iceberg → clickhouse); otherwise the source links straight to ClickHouse.
    """
    edges: list[LineageEdge] = []
    for p in pipelines:
        src = source_ref(settings, p)
        ch = clickhouse_ref(settings, scope, p.target_table)
        if scope.iceberg_namespace:
            ice = iceberg_ref(settings, scope, p.target_table)
            edges.append(LineageEdge(src, ice))
            edges.append(LineageEdge(ice, ch))
        else:
            edges.append(LineageEdge(src, ch))
    return edges


def build_semantic_edges(
    settings: OrchestrationSettings,
    scope: CatalogScope,
    models: list[CatalogSemanticRow],
) -> list[LineageEdge]:
    """``ClickHouse base table → Cube cube`` edges for each of the tenant's models."""
    return [
        LineageEdge(clickhouse_ref(settings, scope, m.base_table), cube_ref(settings, scope, m.name))
        for m in models
    ]


# --- live emission (injected; shells out to the isolated OM-SDK runner) -------


def _emit_lineage(edges: list[LineageEdge], settings: OrchestrationSettings) -> None:
    """Serialise the edges + server creds and post them via the isolated OM-SDK runner.

    The actual ``AddLineageRequest`` posting (and creating any missing source / cube
    endpoint entities) lives in ``catalog_om_runner.py``, run in the OM-SDK venv — the
    SDK can't be imported here. Edges become plain ``{from, to}`` coordinate dicts.
    """
    cat = settings.catalog
    payload = {
        "server": {"host_port": cat.host_port, "jwt_token": cat.jwt_token.get_secret_value()},
        "edges": [{"from": asdict(e.from_ref), "to": asdict(e.to_ref)} for e in edges],
    }
    run_om_runner("lineage", payload, python=cat.runner_python)


def run_lineage(
    settings: OrchestrationSettings,
    scope: CatalogScope,
    pipelines: list[CatalogPipelineRow],
    models: list[CatalogSemanticRow],
    *,
    emit: LineageEmitter = _emit_lineage,
) -> LineageResult:
    """Build the tenant's cross-system edges and emit them (emission injected for tests)."""
    edges = build_pipeline_edges(settings, scope, pipelines) + build_semantic_edges(
        settings, scope, models
    )
    if edges:
        emit(edges, settings)
    return LineageResult(edge_count=len(edges))
