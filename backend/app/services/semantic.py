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
from app.schemas.semantic import (
    SemanticField,
    SemanticModelRead,
    SemanticQueryRequest,
    SemanticValuesRequest,
    SemanticValuesResponse,
)
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
        cube_time_dims: list[dict[str, Any]] = []
        for td in req.time_dimensions:
            entry: dict[str, Any] = {"dimension": td.dimension}
            if td.granularity is not None:
                entry["granularity"] = td.granularity
            if td.cube_date_range is not None:
                entry["dateRange"] = td.cube_date_range
            cube_time_dims.append(entry)
        cube_rows = await self._client.query(
            ctx,
            measures=req.measures,
            dimensions=req.dimensions,
            order=dict(req.order) or None,
            limit=limit,
            filters=cube_filters or None,
            time_dimensions=cube_time_dims or None,
        )

        # Columns: dimensions (incl. time dimensions, under their resolved
        # ``<dimension>.<granularity>`` key) first, then measures — the order the
        # builder maps onto encoding.x (group) + encoding.series[].field (measures).
        time_dim_keys = [td.result_key for td in req.time_dimensions]
        columns: list[str] = [*req.dimensions, *time_dim_keys, *req.measures]
        rows = [self._row_values(cube_row, columns) for cube_row in cube_rows]

        logger.info(
            "Semantic query: tenant_id=%r columns=%r row_count=%d",
            ctx.tenant_id,
            columns,
            len(rows),
        )
        return QueryResponse(columns=columns, rows=rows, row_count=len(rows))

    # ------------------------------------------------------------------
    # Distinct values (filter dropdowns / cascading)
    # ------------------------------------------------------------------

    async def distinct_values(
        self, ctx: TenantContext, req: SemanticValuesRequest
    ) -> SemanticValuesResponse:
        """Return grounded distinct values for a governed dimension (fail closed)."""
        meta = await self._client.meta(ctx)
        allowed_measures, allowed_dimensions = self._allow_lists(meta)
        if req.member not in allowed_dimensions:
            raise SemanticValidationError(f"Unknown dimension: {req.member}")
        allowed_members = allowed_measures | allowed_dimensions
        bad = [c.member for c in req.constraints if c.member not in allowed_members]
        if bad:
            raise SemanticValidationError(
                f"Cannot filter by unknown field(s): {', '.join(sorted(set(bad)))}"
            )
        cube_filters: list[dict[str, Any]] = [
            {"member": c.member, "operator": c.operator, "values": list(c.values)}
            for c in req.constraints
        ]
        if req.search:
            cube_filters.append(
                {"member": req.member, "operator": "contains", "values": [req.search]}
            )
        cap = self._settings.max_filter_values
        limit = min(req.limit, cap) if req.limit is not None else cap
        rows = await self._client.query(
            ctx,
            measures=[],
            dimensions=[req.member],
            order={req.member: "asc"},
            limit=limit,
            filters=cube_filters or None,
        )
        seen: list[str] = []
        seen_set: set[str] = set()
        for row in rows:
            raw = row.get(req.member)
            if raw is None or raw == "":
                continue
            value = str(raw)
            if value not in seen_set:
                seen_set.add(value)
                seen.append(value)
        logger.info(
            "Semantic values: tenant_id=%r member=%r returned %d value(s)",
            ctx.tenant_id, req.member, len(seen),
        )
        return SemanticValuesResponse(values=seen)

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
        # A time dimension's base member must be a governed dimension (a granularity
        # rollup is never a way to reach an ungoverned field). Fail closed.
        bad_time_dims = [
            td.dimension for td in req.time_dimensions if td.dimension not in allowed_dimensions
        ]
        if bad_time_dims:
            raise SemanticValidationError(
                f"Unknown time dimension(s): {', '.join(sorted(set(bad_time_dims)))}"
            )
        # Order keys must be members actually selected in this query — a measure, a
        # dimension, or a time dimension's resolved (granularity) key.
        selected = (
            set(req.measures)
            | set(req.dimensions)
            | {td.result_key for td in req.time_dimensions}
        )
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
