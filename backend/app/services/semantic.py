"""Semantic-layer query service — the governed, structured chart-data path (#9).

The manual chart builder calls this instead of an LLM: it lists the governed models
(Cube cubes/views the tenant may query) and resolves a structured
measures/dimensions request through the Cube client. Two guarantees mirror the AI
path so both stay equally safe:

* **Grounded (golden rule #3).** Every requested measure/dimension is checked
  against the tenant's governed Cube ``/meta`` *before* any query runs. A reference
  Cube does not expose is rejected with a safe 422 — there is no raw-table path.
* **Tenant-scoped (golden rule #2).** All Cube calls take a server-resolved
  ``TenantContext``; the ``clickhouse_db`` claim is set only from it (see
  ``SemanticLayerClient``), never from the request body.

The result is a ``QueryResponse`` whose ``columns`` are ``dimensions + measures`` —
the exact shape the shared ``ChartRenderer`` already consumes for AI charts.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from fastapi import Depends

from app.ai.semantic.client import SemanticLayerClient, get_semantic_layer_client
from app.core.config import Settings, get_settings
from app.schemas.query import QueryResponse
from app.schemas.semantic import SemanticField, SemanticModelRead, SemanticQueryRequest
from app.tenancy.context import TenantContext

logger = logging.getLogger(__name__)


class SemanticValidationError(Exception):
    """A query referenced a measure/dimension outside the governed allow-list.

    Carries a safe, user-facing ``reason``; the router maps it to a 422. Raised
    instead of forwarding an ungrounded reference to Cube so the failure mode is
    identical to the AI path (fail closed, golden rule #3).
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class SemanticService:
    """List governed models and run structured, grounded queries against them."""

    def __init__(self, client: SemanticLayerClient, settings: Settings) -> None:
        self._client = client
        self._settings = settings

    # ------------------------------------------------------------------
    # Models
    # ------------------------------------------------------------------

    async def list_models(self, ctx: TenantContext) -> list[SemanticModelRead]:
        """Return the governed models the tenant may query (from Cube ``/meta``)."""
        meta = await self._client.meta(ctx)
        cubes: list[dict[str, Any]] = meta.get("cubes", [])
        models = [self._to_model(cube) for cube in cubes]
        logger.info(
            "Semantic models: tenant_id=%r returned %d model(s)",
            ctx.tenant_id,
            len(models),
        )
        return models

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    async def query(self, ctx: TenantContext, req: SemanticQueryRequest) -> QueryResponse:
        """Validate a structured request against governed meta, then resolve it.

        Raises ``SemanticValidationError`` (→ 422) if any measure/dimension/order
        key is not exposed by the tenant's governed semantic layer.
        """
        meta = await self._client.meta(ctx)
        allowed_measures, allowed_dimensions = self._allow_lists(meta)

        self._check_grounded(req, allowed_measures, allowed_dimensions)

        limit = self._clamp_limit(req.limit)
        cube_filters = [
            {"member": f.member, "operator": f.operator, "values": list(f.values)}
            for f in req.filters
        ]
        cube_rows = await self._client.query(
            ctx,
            measures=req.measures,
            dimensions=req.dimensions,
            order=dict(req.order) or None,
            limit=limit,
            filters=cube_filters or None,
        )

        # Columns: dimensions first, then measures — the order the builder maps onto
        # encoding.x (dimension) + encoding.series[].field (measures).
        columns: list[str] = [*req.dimensions, *req.measures]
        rows = [self._row_values(cube_row, columns) for cube_row in cube_rows]

        logger.info(
            "Semantic query: tenant_id=%r columns=%r row_count=%d",
            ctx.tenant_id,
            columns,
            len(rows),
        )
        return QueryResponse(columns=columns, rows=rows, row_count=len(rows))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _to_model(cube: dict[str, Any]) -> SemanticModelRead:
        name: str = cube.get("name", "")
        return SemanticModelRead(
            name=name,
            title=cube.get("title", name),
            measures=[SemanticService._to_field(m) for m in cube.get("measures", [])],
            dimensions=[SemanticService._to_field(d) for d in cube.get("dimensions", [])],
        )

    @staticmethod
    def _to_field(member: dict[str, Any]) -> SemanticField:
        name: str = member.get("name", "")
        return SemanticField(
            name=name,
            title=member.get("title", name),
            type=member.get("type", ""),
        )

    @staticmethod
    def _allow_lists(meta: dict[str, Any]) -> tuple[set[str], set[str]]:
        """Collect governed measure + dimension names from the Cube meta response."""
        measures: set[str] = set()
        dimensions: set[str] = set()
        for cube in meta.get("cubes", []):
            measures.update(m.get("name", "") for m in cube.get("measures", []))
            dimensions.update(d.get("name", "") for d in cube.get("dimensions", []))
        measures.discard("")
        dimensions.discard("")
        return measures, dimensions

    def _check_grounded(
        self,
        req: SemanticQueryRequest,
        allowed_measures: set[str],
        allowed_dimensions: set[str],
    ) -> None:
        """Reject any reference outside the governed allow-list (fail closed)."""
        bad_measures = [m for m in req.measures if m not in allowed_measures]
        if bad_measures:
            raise SemanticValidationError(
                f"Unknown measure(s): {', '.join(sorted(bad_measures))}"
            )
        bad_dimensions = [d for d in req.dimensions if d not in allowed_dimensions]
        if bad_dimensions:
            raise SemanticValidationError(
                f"Unknown dimension(s): {', '.join(sorted(bad_dimensions))}"
            )
        # Order keys must be members actually selected in this query.
        selected = set(req.measures) | set(req.dimensions)
        bad_order = [k for k in req.order if k not in selected]
        if bad_order:
            raise SemanticValidationError(
                f"Cannot order by unselected field(s): {', '.join(sorted(bad_order))}"
            )
        # Filter members must be governed (a measure or dimension), but — unlike
        # order — need not be selected: a dashboard may filter on a dimension it
        # doesn't also display. Fail closed on anything outside the allow-list.
        allowed_members = allowed_measures | allowed_dimensions
        bad_filters = [f.member for f in req.filters if f.member not in allowed_members]
        if bad_filters:
            raise SemanticValidationError(
                f"Cannot filter by unknown field(s): {', '.join(sorted(set(bad_filters)))}"
            )

    def _clamp_limit(self, limit: int | None) -> int:
        """Clamp the requested limit to the platform maximum (never exceed it)."""
        cap = self._settings.max_query_rows
        if limit is None:
            return cap
        return min(limit, cap)

    @staticmethod
    def _row_values(cube_row: dict[str, Any], columns: list[str]) -> list[Any]:
        values: list[Any] = []
        for col in columns:
            value = cube_row.get(col)
            # Cast Decimal measures to float so JSON serialisation is safe
            # (mirrors NL→chart); everything else (incl. None) passes through.
            values.append(float(value) if isinstance(value, Decimal) else value)
        return values


def get_semantic_service(
    client: SemanticLayerClient = Depends(get_semantic_layer_client),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> SemanticService:
    """FastAPI dependency: assemble a ``SemanticService`` from request scope."""
    return SemanticService(client=client, settings=settings)
