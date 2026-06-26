# Slice C — Native Filters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Superset-parity native filters to NovaSight dashboards — typed value/time/numeric filters as first-class configurable objects, per-tile scoping, cascading, and grounded drill-by/drill-to-detail — reusing Slice A's query primitives.

**Architecture:** Client-orchestrated, server-validated (Approach 1). Filter *configs* persist on the dashboard (`native_filters`); at view time the dashboard resolves each filter's live selection into Slice-A primitives (`SemanticFilter[]` / time `date_range`) and passes them per-tile to the existing `useChartData` → `/semantic/query` path. The backend grows by one grounded endpoint (`POST /semantic/values`) plus the richer persistence shape; every member is re-validated against the governed Cube allow-list server-side.

**Tech Stack:** Backend — Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0, Alembic, pytest. Frontend — React + TypeScript + Vite, TanStack Query, shadcn/ui + Tailwind, ECharts, dnd-kit, Vitest + RTL.

## Global Constraints

- **No hardcoded config (golden rule #1):** the distinct-values cap comes from `settings.max_filter_values`; no hardcoded members, limits, or paths.
- **Tenancy (golden rule #2):** tenant resolved server-side from `TenantContext`; the client never supplies a tenant id.
- **Grounded/read-only/validated (golden rule #3):** every member (filter target, search, constraints, drill dimension, focus point) is re-validated against the governed Cube allow-list before any query; all reads are read-only; no SQL surface; drill-to-detail is a grounded semantic breakdown, never raw tables.
- **Definition of done:** new code is tested + typed + documented. Backend passes `uv run pytest && uv run ruff check . && uv run mypy app` (run via `backend/.venv/Scripts/*.exe` per the toolchain memo). Frontend passes `pnpm test && pnpm exec tsc --noEmit && pnpm lint`.
- **Fresh-start, no migration:** native filters replace the single-filter bar and the `filter` decoration tile; v1 dashboard `filters` data is dropped (pre-production).
- **Field names are snake_case** across the wire; the TS mirror is field-for-field.
- **Commit after every task** with a `feat(...)`/`test(...)`/`docs(...)` message ending the body with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## File Structure

**Backend**
- `backend/app/core/config.py` — add `max_filter_values` setting (modify).
- `backend/app/schemas/semantic.py` — add `SemanticValuesRequest`/`SemanticValuesResponse` (modify).
- `backend/app/schemas/dashboard.py` — `NativeFilter`/`FilterScope`/`NumericRange`/`NativeFilterKind`; swap `filters`→`native_filters`; drop `"filter"` from `TileKind` (modify).
- `backend/app/models/dashboard.py` — rename column `filters`→`native_filters` (modify).
- `backend/app/services/semantic.py` — `distinct_values()` (modify).
- `backend/app/api/v1/semantic.py` — `POST /semantic/values` (modify).
- `backend/app/services/dashboards.py` — persist/read `native_filters` (modify).
- `backend/alembic/versions/0012_dashboard_native_filters.py` — migration (create).
- `backend/tests/test_native_filters_schema.py`, `test_semantic_values_api.py`, `test_dashboards_native_filters.py` (create).

**Frontend**
- `frontend/src/types/api.ts` — mirror new types; drop `"filter"` from `TileKind` (modify).
- `frontend/src/api/client.ts` — `semanticValues()` (modify).
- `frontend/src/api/hooks.ts` — `useSemanticValues()` + query key (modify).
- `frontend/src/lib/dashboardFilters.ts` — resolution + scoping util (create).
- `frontend/src/lib/useChartData.ts` — time `date_range` override (modify).
- `frontend/src/components/dashboard/DashboardFilterDrawer.tsx` — left drawer + per-filter controls (create; replaces `DashboardFilterBar.tsx`).
- `frontend/src/components/dashboard/NativeFilterEditor.tsx` — add/edit dialog (create).
- `frontend/src/components/dashboard/filterControls/{ValueFilterControl,TimeFilterControl,NumericFilterControl}.tsx` (create).
- `frontend/src/components/chart/DrillByModal.tsx`, `DrillToDetailModal.tsx` (create).
- `frontend/src/components/chart/ChartActionsMenu.tsx` — drill entries (modify).
- `frontend/src/pages/DashboardDetail.tsx`, `components/dashboard/DashboardGrid.tsx`, `DashboardCardTile.tsx` — wire drawer + per-tile application (modify).
- Vitest specs alongside (create/modify): `dashboardFilters.test.ts`, `useChartData.test.ts`, `dashboardFilterDrawer.test.tsx`, `nativeFilterEditor.test.tsx`, `drillModals.test.tsx`.

**Docs**
- `docs/DASHBOARDS.md` (or the existing dashboards page) — native filters, scoping, cascading, drill (modify/create).

---

## Task 1: Backend — `max_filter_values` setting + `NativeFilter` schemas

**Files:**
- Modify: `backend/app/core/config.py:449-451`
- Modify: `backend/app/schemas/dashboard.py`
- Test: `backend/tests/test_native_filters_schema.py` (create)

**Interfaces:**
- Produces: `NativeFilterKind = Literal["value","time","numeric"]`; `NumericRange(min: float|None, max: float|None)`; `FilterScope(mode: Literal["auto","tiles"], tile_ids: list[uuid.UUID])`; `NativeFilter(id, kind, member, label, operator, default_values, date_range, numeric_range, scope, parent_id, required)`; `TileKind` without `"filter"`; `DashboardUpdate.native_filters: list[NativeFilter] | None`; `DashboardRead.native_filters: list[NativeFilter]`. `Settings.max_filter_values: int`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_native_filters_schema.py
"""Validation tests for the NativeFilter config model (Slice C)."""
from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.dashboard import DashboardUpdate, NativeFilter


def _value_filter(**kw: object) -> dict[str, object]:
    base: dict[str, object] = {"id": "f1", "kind": "value", "member": "regional_sales.region"}
    base.update(kw)
    return base


def test_value_filter_minimal_ok() -> None:
    f = NativeFilter(**_value_filter())  # type: ignore[arg-type]
    assert f.operator == "equals"
    assert f.scope.mode == "auto"


def test_value_filter_rejects_comparison_operator() -> None:
    with pytest.raises(ValidationError):
        NativeFilter(**_value_filter(operator="gt"))  # type: ignore[arg-type]


def test_numeric_range_rejects_min_gt_max() -> None:
    with pytest.raises(ValidationError):
        NativeFilter(
            id="n1", kind="numeric", member="regional_sales.sales_rank",
            numeric_range={"min": 10, "max": 1},
        )


def test_absolute_date_range_must_be_two_ordered_dates() -> None:
    with pytest.raises(ValidationError):
        NativeFilter(
            id="t1", kind="time", member="regional_sales.region",
            date_range=["2024-03-01", "2024-01-01"],
        )


def test_scope_tiles_accepts_uuid_list() -> None:
    tid = uuid.uuid4()
    f = NativeFilter(**_value_filter(scope={"mode": "tiles", "tile_ids": [str(tid)]}))  # type: ignore[arg-type]
    assert f.scope.tile_ids == [tid]


def test_dashboard_update_rejects_parent_cycle() -> None:
    with pytest.raises(ValidationError):
        DashboardUpdate(
            native_filters=[
                NativeFilter(**_value_filter(id="a", parent_id="b")),  # type: ignore[arg-type]
                NativeFilter(**_value_filter(id="b", parent_id="a")),  # type: ignore[arg-type]
            ]
        )


def test_dashboard_update_rejects_non_value_parent() -> None:
    with pytest.raises(ValidationError):
        DashboardUpdate(
            native_filters=[
                NativeFilter(id="t", kind="time", member="regional_sales.region"),
                NativeFilter(**_value_filter(id="c", parent_id="t")),  # type: ignore[arg-type]
            ]
        )


def test_dashboard_update_rejects_unknown_parent() -> None:
    with pytest.raises(ValidationError):
        DashboardUpdate(native_filters=[NativeFilter(**_value_filter(id="c", parent_id="missing"))])  # type: ignore[arg-type]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_native_filters_schema.py -q`
Expected: FAIL with `ImportError: cannot import name 'NativeFilter'`.

- [ ] **Step 3: Add the setting**

In `backend/app/core/config.py`, next to `max_query_rows` (line ~450):

```python
    default_page_size: int = 50
    max_query_rows: int = 100_000
    max_upload_mb: int = 100
    # Cap on distinct values returned by POST /semantic/values for a filter dropdown.
    max_filter_values: int = 1000
```

- [ ] **Step 4: Rewrite the dashboard schema models**

In `backend/app/schemas/dashboard.py`, replace the imports + `TileKind` + `DashboardUpdate` + `DashboardRead` regions. Add the new models above `DashboardCreate`:

```python
import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.saved_chart import ChartRead
from app.schemas.semantic import FilterOperator, RelativeDateRange, SemanticRef

# What a dashboard tile holds (#10): a pinned chart, or a decoration object.
# (Slice C removes the standalone "filter" slicer tile — native filters replace it.)
TileKind = Literal["chart", "text", "markdown", "image", "divider"]

# A native filter is one of three typed kinds (Slice C).
NativeFilterKind = Literal["value", "time", "numeric"]


class NumericRange(BaseModel):
    """A numeric filter's [min, max] bounds (either side optional)."""

    min: float | None = None
    max: float | None = None

    @model_validator(mode="after")
    def _min_le_max(self) -> "NumericRange":
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("numeric_range min must not be greater than max")
        return self


class FilterScope(BaseModel):
    """Which tiles a native filter targets. ``auto`` = every cube-compatible tile."""

    mode: Literal["auto", "tiles"] = "auto"
    tile_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)


class NativeFilter(BaseModel):
    """A configured dashboard filter control. Persisted with its *default* selection;
    the live selection is client state seeded from the default."""

    id: str = Field(..., min_length=1, max_length=64)
    kind: NativeFilterKind
    member: SemanticRef
    label: str | None = Field(default=None, max_length=128)
    # value-filter fields
    operator: FilterOperator = "equals"
    default_values: list[str] = Field(default_factory=list, max_length=100)
    # time-filter field (reuses Slice A's relative token | absolute [from, to] model)
    date_range: RelativeDateRange | list[str] | None = None
    # numeric-filter field
    numeric_range: NumericRange | None = None
    scope: FilterScope = Field(default_factory=FilterScope)
    parent_id: str | None = Field(default=None, max_length=64)
    required: bool = False

    @model_validator(mode="after")
    def _validate(self) -> "NativeFilter":
        # A value filter only uses set-membership/substring operators.
        if self.kind == "value" and self.operator in {"set", "notSet", "gt", "gte", "lt", "lte"}:
            raise ValueError("a value filter uses equals/notEquals/contains/notContains")
        if isinstance(self.date_range, list):
            if len(self.date_range) != 2:
                raise ValueError("an absolute date_range must be exactly two ISO dates")
            try:
                start, end = (date.fromisoformat(d) for d in self.date_range)
            except ValueError as exc:
                raise ValueError("date_range entries must be ISO dates (YYYY-MM-DD)") from exc
            if start > end:
                raise ValueError("date_range start must not be after end")
        if self.parent_id is not None and self.parent_id == self.id:
            raise ValueError("a filter cannot be its own parent")
        return self
```

Then rewrite `DashboardUpdate` and `DashboardRead` (replace the existing `filters` fields), and **drop** the now-unused `SemanticFilter` import:

```python
class DashboardUpdate(BaseModel):
    """Body for ``PATCH /dashboards/{id}`` — partial.

    ``native_filters`` (when provided) replaces the dashboard's native filters. Members
    are shape-validated here and re-validated against the governed allow-list when a
    tile runs — persisting a filter never widens data access.
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    native_filters: list[NativeFilter] | None = Field(default=None, max_length=20)

    @model_validator(mode="after")
    def _validate_filters(self) -> "DashboardUpdate":
        if self.native_filters is None:
            return self
        by_id = {f.id: f for f in self.native_filters}
        if len(by_id) != len(self.native_filters):
            raise ValueError("native_filters ids must be unique")
        for f in self.native_filters:
            if f.parent_id is None:
                continue
            parent = by_id.get(f.parent_id)
            if parent is None:
                raise ValueError(f"filter {f.id!r} references unknown parent {f.parent_id!r}")
            if parent.kind != "value":
                raise ValueError("a filter parent must be a value filter")
            seen = {f.id}
            cur: NativeFilter | None = parent
            while cur is not None:
                if cur.id in seen:
                    raise ValueError("native_filters contain a parent cycle")
                seen.add(cur.id)
                cur = by_id.get(cur.parent_id) if cur.parent_id else None
        return self
```

In `DashboardRead`, replace `filters: list[SemanticFilter] = Field(default_factory=list)` with:

```python
    native_filters: list[NativeFilter] = Field(default_factory=list)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_native_filters_schema.py -q`
Expected: PASS (8 passed).

- [ ] **Step 6: Lint + type-check**

Run: `backend/.venv/Scripts/ruff.exe check app/schemas/dashboard.py app/core/config.py && backend/.venv/Scripts/mypy.exe app/schemas/dashboard.py`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add backend/app/core/config.py backend/app/schemas/dashboard.py backend/tests/test_native_filters_schema.py
git commit -m "feat(dashboard): NativeFilter config schema + max_filter_values setting (Slice C)"
```

---

## Task 2: Backend — dashboard persistence (`native_filters`) + migration

**Files:**
- Modify: `backend/app/models/dashboard.py:33-38`
- Modify: `backend/app/services/dashboards.py` (imports, `update`, `_to_read`)
- Create: `backend/alembic/versions/0012_dashboard_native_filters.py`
- Test: `backend/tests/test_dashboards_native_filters.py` (create)

**Interfaces:**
- Consumes: `NativeFilter`, `DashboardUpdate.native_filters` (Task 1).
- Produces: dashboards persist/return `native_filters`; creating a `kind="filter"` tile is rejected (422).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_dashboards_native_filters.py
"""Native-filter persistence + the removal of the 'filter' tile kind (Slice C)."""
from __future__ import annotations

import time
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

_SESSION_SECRET = "test-session-secret-do-not-use-in-production-0123456789"

_FAKE_ENV: dict[str, str] = {
    "ENVIRONMENT": "test",
    "POSTGRES__HOST": "localhost", "POSTGRES__USER": "test",
    "POSTGRES__PASSWORD": "test", "POSTGRES__DB": "test",
    "REDIS__HOST": "localhost",
    "OBJECT_STORE__ENDPOINT_URL": "http://localhost:9000",
    "OBJECT_STORE__ACCESS_KEY": "test", "OBJECT_STORE__SECRET_KEY": "test",
    "OBJECT_STORE__BUCKET": "test",
    "ICEBERG__CATALOG_URI": "http://localhost:8181", "ICEBERG__WAREHOUSE": "s3://test/",
    "CLICKHOUSE__HOST": "localhost", "CLICKHOUSE__PASSWORD": "test",
    "AI__PROVIDER": "openai", "AI__MODEL": "gpt-4o", "AI__API_KEY": "test",
    "AI__PROMPT_TEMPLATE_DIR": "prompts",
    "CUBE__BASE_URL": "http://cube:4000",
    "CUBE__API_SECRET": "test-cube-secret-at-least-32-chars!",
    "AUTH__SESSION_SECRET": _SESSION_SECRET, "AUTH__TENANT_CLAIM": "tenant",
    "SEED_TENANT__SLUG": "local", "SEED_TENANT__NAME": "Local Tenant",
    "SEED_TENANT__ADMIN_EMAIL": "admin@local.test",
}


@pytest.fixture(autouse=True)
def _patch_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in _FAKE_ENV.items():
        monkeypatch.setenv(k, v)


@pytest.fixture()
def client_with_db(session: AsyncSession) -> TestClient:  # type: ignore[return]
    from app.core.config import get_settings
    from app.core.db import get_db
    from app.main import app
    from app.tenancy.registry import TenantRegistry, get_tenant_registry

    get_settings.cache_clear()

    async def _fake_db() -> Any:
        yield session

    async def _fake_registry() -> Any:
        return TenantRegistry(session)

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_tenant_registry] = _fake_registry
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c  # type: ignore[misc]
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def _auth(tenant: str = "local") -> dict[str, str]:
    payload = {"sub": "caller", "email": "c@x", "tenant": tenant, "roles": [],
               "typ": "access", "exp": int(time.time()) + 3600}
    return {"Authorization": f"Bearer {jwt.encode(payload, _SESSION_SECRET, algorithm='HS256')}"}


@pytest.mark.asyncio
async def test_dashboard_round_trips_native_filters(client_with_db: TestClient, make_tenant: Any) -> None:
    await make_tenant("local")
    created = client_with_db.post("/api/v1/dashboards", headers=_auth(), json={"name": "D"})
    assert created.status_code == 201, created.text
    did = created.json()["id"]

    nf = {
        "id": "f1", "kind": "value", "member": "regional_sales.region",
        "operator": "equals", "default_values": ["west"],
        "scope": {"mode": "auto", "tile_ids": []},
    }
    patched = client_with_db.patch(
        f"/api/v1/dashboards/{did}", headers=_auth(), json={"native_filters": [nf]}
    )
    assert patched.status_code == 200, patched.text
    got = client_with_db.get(f"/api/v1/dashboards/{did}", headers=_auth())
    assert got.json()["native_filters"][0]["member"] == "regional_sales.region"
    assert got.json()["native_filters"][0]["default_values"] == ["west"]


@pytest.mark.asyncio
async def test_filter_tile_kind_is_rejected(client_with_db: TestClient, make_tenant: Any) -> None:
    await make_tenant("local")
    did = client_with_db.post("/api/v1/dashboards", headers=_auth(), json={"name": "D"}).json()["id"]
    resp = client_with_db.post(
        f"/api/v1/dashboards/{did}/tiles", headers=_auth(),
        json={"kind": "filter", "content": {"member": "regional_sales.region"}},
    )
    assert resp.status_code == 422, resp.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_dashboards_native_filters.py -q`
Expected: FAIL (the dashboard returns `filters`, not `native_filters`; the filter tile is still accepted).

- [ ] **Step 3: Rename the model column**

In `backend/app/models/dashboard.py`, replace the `filters` column (lines 33-38) with:

```python
    # Native filters (a list of NativeFilter dicts; Slice C). Applied to matching
    # semantic tiles at render; each member is re-validated by the query path. Nullable
    # so the column reads as [] when absent.
    native_filters: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True, default=list
    )
```

Also update the `DashboardTile` docstring to drop the `filter` kind reference (line ~55: change "``image``, ``divider``, or ``filter``" → "``image`` or ``divider``").

- [ ] **Step 4: Update the service**

In `backend/app/services/dashboards.py`: change the import `from app.schemas.semantic import SemanticFilter` to `from app.schemas.dashboard import NativeFilter` (add to the existing dashboard-schema import block instead of importing from semantic). In `update()` replace the `data.filters` block:

```python
        if data.native_filters is not None:
            dashboard.native_filters = [f.model_dump(mode="json") for f in data.native_filters]
```

In `_to_read()` replace the `filters=...` kwarg:

```python
            native_filters=[NativeFilter(**f) for f in (dashboard.native_filters or [])],
```

(`create()` builds `DashboardRead` without the field — `native_filters` defaults to `[]`.)

- [ ] **Step 5: Write the migration**

```python
# backend/alembic/versions/0012_dashboard_native_filters.py
"""dashboard native filters (Slice C)

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-26

Replaces the single ``filters`` JSON column with ``native_filters`` (a list of
NativeFilter config dicts). Fresh-start: the old flat filters are dropped (pre-prod,
no backfill). The drop runs in a batch so it stays portable to SQLite (migration test).
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("dashboards", sa.Column("native_filters", sa.JSON(), nullable=True))
    with op.batch_alter_table("dashboards") as batch:
        batch.drop_column("filters")


def downgrade() -> None:
    op.add_column("dashboards", sa.Column("filters", sa.JSON(), nullable=True))
    with op.batch_alter_table("dashboards") as batch:
        batch.drop_column("native_filters")
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_dashboards_native_filters.py -q`
Expected: PASS (2 passed). Also run the migration test suite if present: `backend/.venv/Scripts/python.exe -m pytest backend/tests -k migration -q` → PASS.

- [ ] **Step 7: Lint + type-check + full dashboard regression**

Run: `backend/.venv/Scripts/ruff.exe check app/models/dashboard.py app/services/dashboards.py && backend/.venv/Scripts/mypy.exe app && backend/.venv/Scripts/python.exe -m pytest backend/tests -k dashboard -q`
Expected: no errors; existing dashboard tests still green (any that asserted `filters` must be updated to `native_filters` in this step).

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/dashboard.py backend/app/services/dashboards.py backend/alembic/versions/0012_dashboard_native_filters.py backend/tests/test_dashboards_native_filters.py
git commit -m "feat(dashboard): persist native_filters, drop legacy filters + filter tile (Slice C)"
```

---

## Task 3: Backend — `POST /semantic/values` distinct-values endpoint

**Files:**
- Modify: `backend/app/schemas/semantic.py` (add request/response models)
- Modify: `backend/app/services/semantic.py` (`distinct_values`)
- Modify: `backend/app/api/v1/semantic.py` (route)
- Test: `backend/tests/test_semantic_values_api.py` (create)

**Interfaces:**
- Produces: `SemanticValuesRequest(member, search, constraints, limit)`, `SemanticValuesResponse(values: list[str])`; `SemanticService.distinct_values(ctx, req) -> SemanticValuesResponse`; route `POST /api/v1/semantic/values`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_semantic_values_api.py
"""Tests for POST /semantic/values — grounded distinct values for filter dropdowns."""
from __future__ import annotations

import time
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.tenancy.context import TenantContext

_SESSION_SECRET = "test-session-secret-do-not-use-in-production-0123456789"
_FAKE_ENV = {
    "ENVIRONMENT": "test", "POSTGRES__HOST": "localhost", "POSTGRES__USER": "test",
    "POSTGRES__PASSWORD": "test", "POSTGRES__DB": "test", "REDIS__HOST": "localhost",
    "OBJECT_STORE__ENDPOINT_URL": "http://localhost:9000", "OBJECT_STORE__ACCESS_KEY": "test",
    "OBJECT_STORE__SECRET_KEY": "test", "OBJECT_STORE__BUCKET": "test",
    "ICEBERG__CATALOG_URI": "http://localhost:8181", "ICEBERG__WAREHOUSE": "s3://test/",
    "CLICKHOUSE__HOST": "localhost", "CLICKHOUSE__PASSWORD": "test",
    "AI__PROVIDER": "openai", "AI__MODEL": "gpt-4o", "AI__API_KEY": "test",
    "AI__PROMPT_TEMPLATE_DIR": "prompts", "CUBE__BASE_URL": "http://cube:4000",
    "CUBE__API_SECRET": "test-cube-secret-at-least-32-chars!",
    "AUTH__SESSION_SECRET": _SESSION_SECRET, "AUTH__TENANT_CLAIM": "tenant",
    "SEED_TENANT__SLUG": "local", "SEED_TENANT__NAME": "Local Tenant",
    "SEED_TENANT__ADMIN_EMAIL": "admin@local.test",
}
_META = {"cubes": [{
    "name": "regional_sales", "title": "Regional Sales",
    "measures": [{"name": "regional_sales.total_amount", "title": "Total", "type": "number"}],
    "dimensions": [{"name": "regional_sales.region", "title": "Region", "type": "string"}],
}]}


class _FakeCube:
    def __init__(self) -> None:
        self.seen_dims: list[list[str]] = []
        self.seen_filters: list[Any] = []
        self.seen_limits: list[int | None] = []
        self.call_count = 0

    async def meta(self, ctx: TenantContext) -> dict[str, Any]:
        return _META

    async def query(self, ctx: TenantContext, *, measures: list[str], dimensions: list[str],
                    order: dict[str, str] | None = None, limit: int | None = None,
                    filters: list[dict[str, Any]] | None = None,
                    time_dimensions: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        self.call_count += 1
        self.seen_dims.append(dimensions)
        self.seen_filters.append(filters)
        self.seen_limits.append(limit)
        return [{"regional_sales.region": "west"}, {"regional_sales.region": "east"},
                {"regional_sales.region": "west"}]  # duplicate proves dedupe


@pytest.fixture(autouse=True)
def _patch_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in _FAKE_ENV.items():
        monkeypatch.setenv(k, v)


@pytest.fixture()
def fake_cube() -> _FakeCube:
    return _FakeCube()


@pytest.fixture()
def client_with_db(session: AsyncSession, fake_cube: _FakeCube) -> TestClient:  # type: ignore[return]
    from app.ai.semantic.client import get_semantic_layer_client
    from app.core.config import get_settings
    from app.core.db import get_db
    from app.main import app
    from app.tenancy.registry import TenantRegistry, get_tenant_registry

    get_settings.cache_clear()

    async def _fake_db() -> Any:
        yield session

    async def _fake_registry() -> Any:
        return TenantRegistry(session)

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_tenant_registry] = _fake_registry
    app.dependency_overrides[get_semantic_layer_client] = lambda: fake_cube
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c  # type: ignore[misc]
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def _auth(tenant: str = "local") -> dict[str, str]:
    payload = {"sub": "c", "email": "c@x", "tenant": tenant, "roles": [],
               "typ": "access", "exp": int(time.time()) + 3600}
    return {"Authorization": f"Bearer {jwt.encode(payload, _SESSION_SECRET, algorithm='HS256')}"}


@pytest.mark.asyncio
async def test_values_grounded_dedup_ordered(client_with_db: TestClient, make_tenant: Any,
                                             fake_cube: _FakeCube) -> None:
    await make_tenant("local")
    resp = client_with_db.post("/api/v1/semantic/values", headers=_auth(),
                               json={"member": "regional_sales.region"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["values"] == ["west", "east"]  # deduped, first-seen order
    assert fake_cube.seen_dims[-1] == ["regional_sales.region"]


@pytest.mark.asyncio
async def test_values_search_becomes_contains_filter(client_with_db: TestClient, make_tenant: Any,
                                                     fake_cube: _FakeCube) -> None:
    await make_tenant("local")
    client_with_db.post("/api/v1/semantic/values", headers=_auth(),
                        json={"member": "regional_sales.region", "search": "wes"})
    assert {"member": "regional_sales.region", "operator": "contains", "values": ["wes"]} \
        in (fake_cube.seen_filters[-1] or [])


@pytest.mark.asyncio
async def test_values_forwards_parent_constraints(client_with_db: TestClient, make_tenant: Any,
                                                  fake_cube: _FakeCube) -> None:
    await make_tenant("local")
    client_with_db.post("/api/v1/semantic/values", headers=_auth(), json={
        "member": "regional_sales.region",
        "constraints": [{"member": "regional_sales.region", "operator": "equals", "values": ["x"]}],
    })
    assert {"member": "regional_sales.region", "operator": "equals", "values": ["x"]} \
        in (fake_cube.seen_filters[-1] or [])


@pytest.mark.asyncio
async def test_values_rejects_ungoverned_member_without_cube_call(
    client_with_db: TestClient, make_tenant: Any, fake_cube: _FakeCube) -> None:
    await make_tenant("local")
    resp = client_with_db.post("/api/v1/semantic/values", headers=_auth(),
                               json={"member": "regional_sales.secret"})
    assert resp.status_code == 422, resp.text
    assert fake_cube.call_count == 0


@pytest.mark.asyncio
async def test_values_clamps_limit_to_cap(client_with_db: TestClient, make_tenant: Any,
                                          fake_cube: _FakeCube) -> None:
    from app.core.config import get_settings
    await make_tenant("local")
    cap = get_settings().max_filter_values
    client_with_db.post("/api/v1/semantic/values", headers=_auth(),
                        json={"member": "regional_sales.region", "limit": 10_000_000})
    assert fake_cube.seen_limits[-1] == cap
```

- [ ] **Step 2: Run test to verify it fails**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_semantic_values_api.py -q`
Expected: FAIL (404 — route not defined).

- [ ] **Step 3: Add the schemas**

In `backend/app/schemas/semantic.py`, append after `SemanticQueryRequest`:

```python
class SemanticValuesRequest(BaseModel):
    """Request distinct values for a governed dimension (filter dropdown / cascading).

    ``member`` must be a governed dimension. ``search`` is an optional substring
    (server-side typeahead → a ``contains`` filter). ``constraints`` are parent-filter
    selections (cascading). ``limit`` is clamped to ``settings.max_filter_values``.
    """

    member: SemanticRef
    search: str | None = Field(default=None, max_length=128)
    constraints: list[SemanticFilter] = Field(default_factory=list, max_length=20)
    limit: int | None = Field(default=None, ge=1)


class SemanticValuesResponse(BaseModel):
    """Distinct values for a dimension (deduped, capped, ordered)."""

    values: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Add the service method**

In `backend/app/services/semantic.py`, import the new schemas in the existing `from app.schemas.semantic import ...` line, then add to `SemanticService`:

```python
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
```

- [ ] **Step 5: Add the route**

In `backend/app/api/v1/semantic.py`, import `SemanticValuesRequest, SemanticValuesResponse` from `app.schemas.semantic`, then add:

```python
@router.post(
    "/values",
    response_model=SemanticValuesResponse,
    responses={
        422: {"description": "The dimension/constraint is not in the governed allow-list"},
        503: {"description": "Semantic layer temporarily unavailable"},
    },
    summary="List grounded distinct values for a governed dimension",
)
async def semantic_values(
    payload: SemanticValuesRequest,
    ctx: TenantContext = Depends(get_tenant_context),  # noqa: B008
    svc: SemanticService = Depends(get_semantic_service),  # noqa: B008
) -> SemanticValuesResponse:
    """Return distinct values for a filter dropdown (grounded, tenant-scoped)."""
    try:
        return await svc.distinct_values(ctx, payload)
    except SemanticValidationError as exc:
        logger.info("Semantic values rejected: tenant_id=%r reason=%r", ctx.tenant_id, exc.reason)
        raise HTTPException(status_code=422, detail=exc.reason) from exc
    except CubeAuthError as exc:
        logger.warning("Semantic values Cube auth error: tenant_id=%r", ctx.tenant_id)
        raise HTTPException(status_code=503, detail="Semantic layer is temporarily unavailable. Please try again.") from exc
    except CubeQueryError as exc:
        logger.error("Semantic values Cube query error: tenant_id=%r", ctx.tenant_id)
        raise HTTPException(status_code=503, detail="Semantic layer returned an error. Please try again.") from exc
```

- [ ] **Step 6: Run tests + lint + type-check**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_semantic_values_api.py -q && backend/.venv/Scripts/ruff.exe check app/api/v1/semantic.py app/services/semantic.py app/schemas/semantic.py && backend/.venv/Scripts/mypy.exe app`
Expected: PASS (5 passed); no lint/type errors.

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/semantic.py backend/app/services/semantic.py backend/app/api/v1/semantic.py backend/tests/test_semantic_values_api.py
git commit -m "feat(semantic): grounded POST /semantic/values for filter dropdowns + cascading (Slice C)"
```

---

## Task 4: Frontend — type mirror + client fn + `useSemanticValues`

**Files:**
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/hooks.ts`
- Test: `frontend/src/test/semanticValues.test.ts` (create)

**Interfaces:**
- Produces (TS): `NativeFilterKind`, `NumericRange`, `FilterScope`, `NativeFilter`, `SemanticValuesRequest`, `SemanticValuesResponse`; `DashboardRead.native_filters`, `DashboardUpdate.native_filters`; `TileKind` without `"filter"`; `semanticValues(req)`; `useSemanticValues(req|null)`.

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/test/semanticValues.test.ts
import { describe, expect, it, vi, beforeEach } from "vitest";

import { semanticValues } from "@/api/client";

describe("semanticValues client", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("POSTs to /semantic/values and returns values", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ values: ["west", "east"] }), {
        status: 200, headers: { "Content-Type": "application/json" },
      })
    );
    const out = await semanticValues({ member: "regional_sales.region", search: "we" });
    expect(out.values).toEqual(["west", "east"]);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/semantic/values");
    expect(JSON.parse(String(init?.body))).toMatchObject({ member: "regional_sales.region", search: "we" });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm exec vitest run src/test/semanticValues.test.ts`
Expected: FAIL (`semanticValues` is not exported).

- [ ] **Step 3: Add the TS types**

In `frontend/src/types/api.ts`: change `TileKind` (line 830) to drop `"filter"`:

```ts
export type TileKind = "chart" | "text" | "markdown" | "image" | "divider";
```

Add to the Semantic-layer section (after `SemanticQueryRequest`, ~line 422):

```ts
/** Request distinct values for a governed dimension (filter dropdown / cascading). */
export interface SemanticValuesRequest {
  member: string;
  /** Optional substring typeahead → server-side `contains` filter. */
  search?: string | null;
  /** Parent-filter selections constraining the values (cascading). */
  constraints?: SemanticFilter[];
  limit?: number;
}

/** Distinct values for a dimension (deduped, capped, ordered). */
export interface SemanticValuesResponse {
  values: string[];
}
```

Add to the Dashboards section (after `SavedChartRead` / before `DashboardTileRead`):

```ts
/** One of the three native filter kinds (Slice C). */
export type NativeFilterKind = "value" | "time" | "numeric";

/** A numeric filter's [min, max] bounds (either side optional). */
export interface NumericRange {
  min?: number | null;
  max?: number | null;
}

/** Which tiles a native filter targets. `auto` = every cube-compatible tile. */
export interface FilterScope {
  mode: "auto" | "tiles";
  tile_ids: string[];
}

/** A configured dashboard filter control (persisted with its default selection). */
export interface NativeFilter {
  id: string;
  kind: NativeFilterKind;
  member: string;
  label?: string | null;
  /** value filters: equals/notEquals/contains/notContains. */
  operator?: SemanticFilterOperator;
  default_values?: string[];
  /** time filters: relative token or absolute [from, to] ISO pair. */
  date_range?: RelativeDateRange | string[] | null;
  /** numeric filters. */
  numeric_range?: NumericRange | null;
  scope?: FilterScope;
  /** value filter whose selection constrains this one's options (cascading). */
  parent_id?: string | null;
  required?: boolean;
}
```

Replace `DashboardRead.filters` (line ~869) and `DashboardUpdate.filters` (line ~882) with `native_filters?: NativeFilter[];` (and update the doc comment to "Native filters applied across the dashboard's matching semantic tiles.").

- [ ] **Step 4: Add the client function**

In `frontend/src/api/client.ts`, after `querySemantic` (line ~463), import the types and add:

```ts
/** POST /semantic/values — grounded distinct values for a filter dropdown. */
export async function semanticValues(
  request: SemanticValuesRequest
): Promise<SemanticValuesResponse> {
  return apiFetch<SemanticValuesResponse>(
    "/semantic/values",
    { method: "POST", body: JSON.stringify(request) },
    { "Content-Type": "application/json" }
  );
}
```

(Add `SemanticValuesRequest, SemanticValuesResponse` to the existing `@/types/api` import in client.ts.)

- [ ] **Step 5: Add the hook + query key**

In `frontend/src/api/hooks.ts`: add `semanticValues` to the `./client` import; add `SemanticValuesRequest` to the `@/types/api` import; add a query key and hook:

```ts
// in queryKeys:
  semanticValues: (req: SemanticValuesRequest) => ["semantic", "values", req] as const,
```

```ts
// after useSemanticQuery:
/**
 * Query: grounded distinct values for a filter dropdown. Disabled until a request is
 * provided (a value filter is open) so it never runs on mount for non-value filters.
 */
export function useSemanticValues(request: SemanticValuesRequest | null) {
  return useQuery({
    queryKey:
      request !== null ? queryKeys.semanticValues(request) : (["noop"] as const),
    queryFn: () => {
      if (!request) throw new Error("a semantic values request is required");
      return semanticValues(request);
    },
    enabled: request !== null,
    staleTime: 60_000,
    retry: 0,
  });
}
```

- [ ] **Step 6: Run tests + tsc**

Run: `cd frontend && pnpm exec vitest run src/test/semanticValues.test.ts && pnpm exec tsc --noEmit`
Expected: PASS; tsc reports errors only where existing code still reads `dashboard.filters` (fixed in Task 10) — if tsc fails solely on `DashboardDetail.tsx`/`DashboardFilterBar.tsx`/`DashboardCardTile.tsx`, that's expected and resolved in later tasks. To keep this task green in isolation, leave those files until Task 10; if tsc must pass now, temporarily cast. Prefer: land Tasks 4–10 before the next full `tsc`.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/types/api.ts frontend/src/api/client.ts frontend/src/api/hooks.ts frontend/src/test/semanticValues.test.ts
git commit -m "feat(api): mirror NativeFilter + /semantic/values types, add useSemanticValues (Slice C)"
```

---

## Task 5: Frontend — filter resolution + scoping util

**Files:**
- Create: `frontend/src/lib/dashboardFilters.ts`
- Test: `frontend/src/test/dashboardFilters.test.ts` (create)

**Interfaces:**
- Consumes: `NativeFilter`, `SemanticFilter`, `DashboardTileRead`, `RelativeDateRange` (Task 4).
- Produces:
  - `type FilterSelection = { kind: "value"; values: string[] } | { kind: "time"; date_range: RelativeDateRange | string[] | null } | { kind: "numeric"; min: number | null; max: number | null }`
  - `type FilterSelections = Record<string, FilterSelection>`
  - `cubeOf(member: string): string | undefined`
  - `defaultSelection(f: NativeFilter): FilterSelection`
  - `filterAppliesToTile(f: NativeFilter, tile: DashboardTileRead): boolean`
  - `resolveTileFilters(filters: NativeFilter[], selections: FilterSelections, tile: DashboardTileRead): { filters: SemanticFilter[]; dateRanges: Record<string, RelativeDateRange | string[]> }`

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/test/dashboardFilters.test.ts
import { describe, expect, it } from "vitest";

import {
  cubeOf, defaultSelection, filterAppliesToTile, resolveTileFilters,
} from "@/lib/dashboardFilters";
import type { DashboardTileRead, NativeFilter } from "@/types/api";

function tile(metric: string, id = "t1"): DashboardTileRead {
  return {
    id, kind: "chart", chart_id: "c", content: null, title: null,
    position: 0, x: 0, y: 0, w: 6, h: 4,
    chart: {
      id: "c", name: "C", source_kind: "semantic", source_ref: null, owner_id: null,
      created_at: "", updated_at: "",
      spec: { type: "bar", query: { metric_refs: [metric] }, encoding: { x: "regional_sales.region", series: [{ field: metric }] } },
    },
  } as DashboardTileRead;
}

const valueF: NativeFilter = { id: "f1", kind: "value", member: "regional_sales.region", operator: "equals" };
const numericF: NativeFilter = { id: "f2", kind: "numeric", member: "regional_sales.sales_rank" };
const timeF: NativeFilter = { id: "f3", kind: "time", member: "regional_sales.region" };

describe("cubeOf", () => {
  it("returns the prefix before the first dot", () => {
    expect(cubeOf("regional_sales.region")).toBe("regional_sales");
    expect(cubeOf("nodot")).toBeUndefined();
  });
});

describe("filterAppliesToTile", () => {
  it("auto scope applies to a cube-compatible tile", () => {
    expect(filterAppliesToTile(valueF, tile("regional_sales.total_amount"))).toBe(true);
  });
  it("never applies to an incompatible cube even in tile scope", () => {
    const scoped: NativeFilter = { ...valueF, scope: { mode: "tiles", tile_ids: ["t1"] } };
    expect(filterAppliesToTile(scoped, tile("other_cube.x"))).toBe(false);
  });
  it("tile scope excludes tiles not in tile_ids", () => {
    const scoped: NativeFilter = { ...valueF, scope: { mode: "tiles", tile_ids: ["other"] } };
    expect(filterAppliesToTile(scoped, tile("regional_sales.total_amount"))).toBe(false);
  });
});

describe("resolveTileFilters", () => {
  const t = tile("regional_sales.total_amount");
  it("value selection → a SemanticFilter", () => {
    const out = resolveTileFilters([valueF], { f1: { kind: "value", values: ["west", "east"] } }, t);
    expect(out.filters).toEqual([{ member: "regional_sales.region", operator: "equals", values: ["west", "east"] }]);
  });
  it("empty value selection contributes nothing", () => {
    const out = resolveTileFilters([valueF], { f1: { kind: "value", values: [] } }, t);
    expect(out.filters).toEqual([]);
  });
  it("numeric selection → gte/lte filters", () => {
    const out = resolveTileFilters([numericF], { f2: { kind: "numeric", min: 1, max: 5 } }, t);
    expect(out.filters).toEqual([
      { member: "regional_sales.sales_rank", operator: "gte", values: ["1"] },
      { member: "regional_sales.sales_rank", operator: "lte", values: ["5"] },
    ]);
  });
  it("time selection → a dateRange keyed by member", () => {
    const out = resolveTileFilters([timeF], { f3: { kind: "time", date_range: "last_30_days" } }, t);
    expect(out.dateRanges).toEqual({ "regional_sales.region": "last_30_days" });
  });
});

describe("defaultSelection", () => {
  it("seeds a value selection from default_values", () => {
    expect(defaultSelection({ ...valueF, default_values: ["west"] })).toEqual({ kind: "value", values: ["west"] });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm exec vitest run src/test/dashboardFilters.test.ts`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement the util**

```ts
// frontend/src/lib/dashboardFilters.ts
/**
 * Native-filter resolution + scoping (Slice C).
 *
 * Native filters persist as configs on the dashboard; at view time their live
 * selections resolve to Slice-A primitives (SemanticFilter[] / a time date_range) and
 * are applied per-tile. A filter only touches a tile whose cube contains its member
 * (the safety invariant that keeps a filter from breaking an unrelated tile).
 */
import type {
  DashboardTileRead, NativeFilter, RelativeDateRange, SemanticFilter,
} from "@/types/api";

export type FilterSelection =
  | { kind: "value"; values: string[] }
  | { kind: "time"; date_range: RelativeDateRange | string[] | null }
  | { kind: "numeric"; min: number | null; max: number | null };

export type FilterSelections = Record<string, FilterSelection>;

/** The cube a fully-qualified member belongs to (the part before the first dot). */
export function cubeOf(member: string | undefined): string | undefined {
  return member?.includes(".") ? member.split(".")[0] : undefined;
}

/** The cubes a chart tile reads (from its metric refs). */
function tileCubes(tile: DashboardTileRead): Set<string> {
  const cubes = new Set<string>();
  for (const m of tile.chart?.spec.query.metric_refs ?? []) {
    const c = cubeOf(m);
    if (c) cubes.add(c);
  }
  return cubes;
}

/** The default live selection a filter's config seeds. */
export function defaultSelection(f: NativeFilter): FilterSelection {
  if (f.kind === "value") return { kind: "value", values: f.default_values ?? [] };
  if (f.kind === "time") return { kind: "time", date_range: f.date_range ?? null };
  return { kind: "numeric", min: f.numeric_range?.min ?? null, max: f.numeric_range?.max ?? null };
}

/**
 * Whether a filter applies to a tile. The cube-compatibility check ALWAYS holds, so a
 * filter can never break an unrelated tile. With tile-scope it must also be listed.
 */
export function filterAppliesToTile(f: NativeFilter, tile: DashboardTileRead): boolean {
  if (tile.kind !== "chart") return false;
  const cube = cubeOf(f.member);
  if (!cube || !tileCubes(tile).has(cube)) return false;
  const scope = f.scope ?? { mode: "auto", tile_ids: [] };
  if (scope.mode === "tiles") return scope.tile_ids.includes(tile.id);
  return true;
}

/** Resolve all applicable filters for one tile into Slice-A primitives. */
export function resolveTileFilters(
  filters: NativeFilter[],
  selections: FilterSelections,
  tile: DashboardTileRead
): { filters: SemanticFilter[]; dateRanges: Record<string, RelativeDateRange | string[]> } {
  const out: SemanticFilter[] = [];
  const dateRanges: Record<string, RelativeDateRange | string[]> = {};
  for (const f of filters) {
    if (!filterAppliesToTile(f, tile)) continue;
    const sel = selections[f.id] ?? defaultSelection(f);
    if (sel.kind === "value" && sel.values.length > 0) {
      out.push({ member: f.member, operator: f.operator ?? "equals", values: sel.values });
    } else if (sel.kind === "numeric") {
      if (sel.min !== null) out.push({ member: f.member, operator: "gte", values: [String(sel.min)] });
      if (sel.max !== null) out.push({ member: f.member, operator: "lte", values: [String(sel.max)] });
    } else if (sel.kind === "time" && sel.date_range) {
      dateRanges[f.member] = sel.date_range;
    }
  }
  return { filters: out, dateRanges };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && pnpm exec vitest run src/test/dashboardFilters.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/dashboardFilters.ts frontend/src/test/dashboardFilters.test.ts
git commit -m "feat(dashboard): native-filter resolution + per-tile scoping util (Slice C)"
```

---

## Task 6: Frontend — `useChartData` time `date_range` override

**Files:**
- Modify: `frontend/src/lib/useChartData.ts`
- Test: `frontend/src/test/useChartData.test.ts` (create or extend)

**Interfaces:**
- Consumes: `resolveTileFilters` output shape (a `dateRanges` map). Existing `buildSemanticRequest(spec, viewFilters)`.
- Produces: `buildSemanticRequest(spec, viewFilters?, dateRangeOverrides?)` where `dateRangeOverrides?: Record<string, RelativeDateRange | string[]>` keyed by time-dimension member; `useChartData(spec, filters?, dateRangeOverrides?)`.

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/test/useChartData.test.ts
import { describe, expect, it } from "vitest";

import { buildSemanticRequest } from "@/lib/useChartData";
import type { ChartSpec } from "@/types/api";

const spec: ChartSpec = {
  type: "line",
  query: {
    metric_refs: ["regional_sales.total_amount"],
    time_dimensions: [{ dimension: "regional_sales.order_date", granularity: "month" }],
  },
  encoding: { x: "regional_sales.order_date.month", series: [{ field: "regional_sales.total_amount" }] },
};

describe("buildSemanticRequest date_range override", () => {
  it("injects a view-time date_range onto the matching time dimension", () => {
    const req = buildSemanticRequest(spec, undefined, { "regional_sales.order_date": "last_30_days" });
    expect(req?.time_dimensions?.[0].date_range).toBe("last_30_days");
  });

  it("leaves time dimensions unchanged when no override matches", () => {
    const req = buildSemanticRequest(spec, undefined, { "other.dim": "last_7_days" });
    expect(req?.time_dimensions?.[0].date_range).toBeUndefined();
  });

  it("merges spec + view-time filters (spec first)", () => {
    const withFilter: ChartSpec = { ...spec, query: { ...spec.query, filters: [{ member: "regional_sales.region", operator: "equals", values: ["west"] }] } };
    const req = buildSemanticRequest(withFilter, [{ member: "regional_sales.region", operator: "equals", values: ["east"] }]);
    expect(req?.filters).toHaveLength(2);
    expect(req?.filters?.[0].values).toEqual(["west"]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm exec vitest run src/test/useChartData.test.ts`
Expected: FAIL (`buildSemanticRequest` takes 2 args; override ignored).

- [ ] **Step 3: Implement the override**

In `frontend/src/lib/useChartData.ts`, add the import and update the signatures:

```ts
import type {
  ChartSpec, QueryRequest, RelativeDateRange, SemanticFilter, SemanticQueryRequest,
} from "@/types/api";
```

Replace `buildSemanticRequest`:

```ts
export function buildSemanticRequest(
  spec: ChartSpec | null,
  viewFilters?: SemanticFilter[],
  dateRangeOverrides?: Record<string, RelativeDateRange | string[]>
): SemanticQueryRequest | null {
  const metricRefs = spec?.query.metric_refs ?? [];
  if (!spec || metricRefs.length === 0) return null;

  const rawTimeDimensions = spec.query.time_dimensions ?? [];
  // Apply any view-time date_range override to the matching time dimension (by member).
  const timeDimensions = rawTimeDimensions.map((td) =>
    dateRangeOverrides && dateRangeOverrides[td.dimension] !== undefined
      ? { ...td, date_range: dateRangeOverrides[td.dimension] }
      : td
  );
  const hasTimeDim = timeDimensions.length > 0;
  const plainDimensions =
    spec.query.dimensions && spec.query.dimensions.length > 0
      ? spec.query.dimensions
      : hasTimeDim || !spec.encoding.x
        ? []
        : [spec.encoding.x];

  const specFilters = spec.query.filters ?? [];
  const filters = [...specFilters, ...(viewFilters ?? [])];

  return {
    measures: metricRefs,
    dimensions: plainDimensions,
    ...(hasTimeDim ? { time_dimensions: timeDimensions } : {}),
    ...(spec.query.order && Object.keys(spec.query.order).length > 0
      ? { order: spec.query.order }
      : {}),
    limit: spec.query.limit ?? DEFAULT_LIMIT,
    ...(filters.length > 0 ? { filters } : {}),
  };
}
```

Update `useChartData`:

```ts
export function useChartData(
  spec: ChartSpec | null,
  filters?: SemanticFilter[],
  dateRangeOverrides?: Record<string, RelativeDateRange | string[]>
) {
  const isSemantic = (spec?.query.metric_refs ?? []).length > 0;
  const semanticRequest = buildSemanticRequest(spec, filters, dateRangeOverrides);
  // ...unchanged below...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && pnpm exec vitest run src/test/useChartData.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/useChartData.ts frontend/src/test/useChartData.test.ts
git commit -m "feat(chart): useChartData view-time date_range override for native time filters (Slice C)"
```

---

## Task 7: Frontend — per-filter controls + `DashboardFilterDrawer` (view mode)

**Files:**
- Create: `frontend/src/components/dashboard/filterControls/ValueFilterControl.tsx`
- Create: `frontend/src/components/dashboard/filterControls/TimeFilterControl.tsx`
- Create: `frontend/src/components/dashboard/filterControls/NumericFilterControl.tsx`
- Create: `frontend/src/components/dashboard/DashboardFilterDrawer.tsx`
- Delete: `frontend/src/components/dashboard/DashboardFilterBar.tsx` (and its test) — replaced
- Test: `frontend/src/test/dashboardFilterDrawer.test.tsx` (create)

**Interfaces:**
- Consumes: `useSemanticValues` (Task 4); `FilterSelection`/`FilterSelections`/`defaultSelection` (Task 5); `NativeFilter`.
- Produces:
  - `ValueFilterControl({ filter, selection, onChange, constraints })` — multi-select fed by `useSemanticValues`.
  - `TimeFilterControl({ filter, selection, onChange })` — preset/custom/none (reuse the builder's time-range control if extractable; otherwise a local `Select` of `RelativeDateRange` tokens + a Custom two-date mode).
  - `NumericFilterControl({ filter, selection, onChange })` — min/max inputs.
  - `DashboardFilterDrawer({ filters, selections, onSelectionChange, onClearAll, editing, onAddFilter, onEditFilter })` — collapsible left drawer rendering one control per filter; in edit mode shows Add/Edit affordances.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/test/dashboardFilterDrawer.test.tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { DashboardFilterDrawer } from "@/components/dashboard/DashboardFilterDrawer";
import type { NativeFilter } from "@/types/api";

vi.mock("@/api/hooks", () => ({
  useSemanticValues: () => ({ data: { values: ["west", "east"] }, isLoading: false }),
}));

const filters: NativeFilter[] = [
  { id: "f1", kind: "value", member: "regional_sales.region", operator: "equals", label: "Region" },
];

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient();
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe("DashboardFilterDrawer", () => {
  it("renders a control per filter and a Clear all", () => {
    wrap(
      <DashboardFilterDrawer
        filters={filters}
        selections={{}}
        onSelectionChange={() => {}}
        onClearAll={() => {}}
        editing={false}
      />
    );
    expect(screen.getByText("Region")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /clear all/i })).toBeInTheDocument();
  });

  it("Clear all fires the callback", () => {
    const onClearAll = vi.fn();
    wrap(
      <DashboardFilterDrawer filters={filters} selections={{}} onSelectionChange={() => {}} onClearAll={onClearAll} editing={false} />
    );
    fireEvent.click(screen.getByRole("button", { name: /clear all/i }));
    expect(onClearAll).toHaveBeenCalled();
  });

  it("shows Add filter only in edit mode", () => {
    const { rerender } = wrap(
      <DashboardFilterDrawer filters={filters} selections={{}} onSelectionChange={() => {}} onClearAll={() => {}} editing={false} onAddFilter={() => {}} />
    );
    expect(screen.queryByRole("button", { name: /add filter/i })).not.toBeInTheDocument();
    const qc = new QueryClient();
    rerender(
      <QueryClientProvider client={qc}>
        <DashboardFilterDrawer filters={filters} selections={{}} onSelectionChange={() => {}} onClearAll={() => {}} editing onAddFilter={() => {}} />
      </QueryClientProvider>
    );
    expect(screen.getByRole("button", { name: /add filter/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm exec vitest run src/test/dashboardFilterDrawer.test.tsx`
Expected: FAIL (component not found).

- [ ] **Step 3: Implement `ValueFilterControl`**

```tsx
// frontend/src/components/dashboard/filterControls/ValueFilterControl.tsx
/**
 * ValueFilterControl — multi-select for a value native filter, fed by grounded
 * /semantic/values. `constraints` carry the parent selection for cascading.
 */
import { useState } from "react";

import { useSemanticValues } from "@/api/hooks";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import type { NativeFilter, SemanticFilter } from "@/types/api";

interface Props {
  filter: NativeFilter;
  values: string[];
  onChange: (values: string[]) => void;
  constraints?: SemanticFilter[];
  enabled?: boolean;
}

export function ValueFilterControl({ filter, values, onChange, constraints, enabled = true }: Props) {
  const [search, setSearch] = useState("");
  const { data } = useSemanticValues(
    enabled ? { member: filter.member, search: search || null, constraints } : null
  );
  const options = data?.values ?? [];

  const toggle = (v: string) =>
    onChange(values.includes(v) ? values.filter((x) => x !== v) : [...values, v]);

  return (
    <div className="space-y-1.5">
      <Input
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search…"
        aria-label={`Search ${filter.label ?? filter.member}`}
        className="h-8"
      />
      <div className="flex max-h-40 flex-col gap-1 overflow-auto">
        {options.map((o) => (
          <label key={o} className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={values.includes(o)} onChange={() => toggle(o)} />
            {o}
          </label>
        ))}
        {options.length === 0 && <span className="text-xs text-muted-foreground">No values</span>}
      </div>
      {values.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {values.map((v) => (
            <Badge key={v} variant="secondary" className="cursor-pointer" onClick={() => toggle(v)}>
              {v} ✕
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Implement `TimeFilterControl` and `NumericFilterControl`**

```tsx
// frontend/src/components/dashboard/filterControls/TimeFilterControl.tsx
import { Select } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import type { RelativeDateRange } from "@/types/api";

const PRESETS: RelativeDateRange[] = [
  "last_7_days", "last_30_days", "last_90_days", "this_month", "last_month",
  "this_quarter", "last_quarter", "this_year", "last_year",
];

interface Props {
  value: RelativeDateRange | string[] | null;
  onChange: (next: RelativeDateRange | string[] | null) => void;
  label: string;
}

export function TimeFilterControl({ value, onChange, label }: Props) {
  const isCustom = Array.isArray(value);
  const mode = value === null ? "none" : isCustom ? "custom" : "preset";
  const [from, to] = Array.isArray(value) ? value : ["", ""];

  return (
    <div className="space-y-1.5">
      <Select
        aria-label={`${label} range`}
        value={mode === "preset" ? (value as string) : mode}
        onChange={(e) => {
          const v = e.target.value;
          if (v === "none") onChange(null);
          else if (v === "custom") onChange(["", ""]);
          else onChange(v as RelativeDateRange);
        }}
        className="h-8"
      >
        <option value="none">No filter</option>
        {PRESETS.map((p) => (
          <option key={p} value={p}>{p.replace(/_/g, " ")}</option>
        ))}
        <option value="custom">Custom…</option>
      </Select>
      {isCustom && (
        <div className="flex gap-1">
          <Input type="date" value={from} onChange={(e) => onChange([e.target.value, to])} aria-label={`${label} from`} className="h-8" />
          <Input type="date" value={to} onChange={(e) => onChange([from, e.target.value])} aria-label={`${label} to`} className="h-8" />
        </div>
      )}
    </div>
  );
}
```

```tsx
// frontend/src/components/dashboard/filterControls/NumericFilterControl.tsx
import { Input } from "@/components/ui/input";

interface Props {
  min: number | null;
  max: number | null;
  onChange: (next: { min: number | null; max: number | null }) => void;
  label: string;
}

const parse = (s: string): number | null => (s.trim() === "" ? null : Number(s));

export function NumericFilterControl({ min, max, onChange, label }: Props) {
  return (
    <div className="flex gap-1">
      <Input type="number" value={min ?? ""} onChange={(e) => onChange({ min: parse(e.target.value), max })} placeholder="min" aria-label={`${label} min`} className="h-8" />
      <Input type="number" value={max ?? ""} onChange={(e) => onChange({ min, max: parse(e.target.value) })} placeholder="max" aria-label={`${label} max`} className="h-8" />
    </div>
  );
}
```

- [ ] **Step 5: Implement `DashboardFilterDrawer`**

```tsx
// frontend/src/components/dashboard/DashboardFilterDrawer.tsx
/**
 * DashboardFilterDrawer — collapsible left drawer of native filters (Slice C).
 * One control per filter (value/time/numeric). In edit mode it exposes Add/Edit.
 * Cascading: a child value filter's options are constrained by its parent's selection.
 */
import { useState } from "react";
import { ChevronLeft, ChevronRight, Filter, Pencil, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/cn";
import { ValueFilterControl } from "./filterControls/ValueFilterControl";
import { TimeFilterControl } from "./filterControls/TimeFilterControl";
import { NumericFilterControl } from "./filterControls/NumericFilterControl";
import { defaultSelection } from "@/lib/dashboardFilters";
import type { FilterSelection, FilterSelections } from "@/lib/dashboardFilters";
import type { NativeFilter, SemanticFilter } from "@/types/api";

interface Props {
  filters: NativeFilter[];
  selections: FilterSelections;
  onSelectionChange: (id: string, sel: FilterSelection) => void;
  onClearAll: () => void;
  editing: boolean;
  onAddFilter?: () => void;
  onEditFilter?: (id: string) => void;
}

/** Parent selection of a value filter expressed as a constraint for cascading. */
function parentConstraints(filter: NativeFilter, all: NativeFilter[], selections: FilterSelections): SemanticFilter[] {
  if (!filter.parent_id) return [];
  const parent = all.find((f) => f.id === filter.parent_id);
  if (!parent) return [];
  const sel = selections[parent.id] ?? defaultSelection(parent);
  if (sel.kind === "value" && sel.values.length > 0) {
    return [{ member: parent.member, operator: parent.operator ?? "equals", values: sel.values }];
  }
  return [];
}

export function DashboardFilterDrawer({
  filters, selections, onSelectionChange, onClearAll, editing, onAddFilter, onEditFilter,
}: Props) {
  const [open, setOpen] = useState(true);

  if (filters.length === 0 && !editing) return null;

  return (
    <aside className={cn("shrink-0 border-r bg-card/40 transition-all", open ? "w-64" : "w-10")}>
      <div className="flex items-center justify-between p-2">
        {open && (
          <span className="flex items-center gap-1.5 text-sm font-medium">
            <Filter className="h-4 w-4" aria-hidden /> Filters
          </span>
        )}
        <Button variant="ghost" size="icon" aria-label={open ? "Collapse filters" : "Expand filters"} onClick={() => setOpen((v) => !v)}>
          {open ? <ChevronLeft className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        </Button>
      </div>

      {open && (
        <div className="space-y-4 p-3">
          {filters.map((f) => {
            const sel = selections[f.id] ?? defaultSelection(f);
            return (
              <div key={f.id} className="space-y-1">
                <div className="flex items-center justify-between">
                  <Label className="text-xs text-muted-foreground">
                    {f.label ?? f.member}{f.required ? " *" : ""}
                  </Label>
                  {editing && onEditFilter && (
                    <button type="button" aria-label={`Edit ${f.label ?? f.member}`} onClick={() => onEditFilter(f.id)} className="text-muted-foreground hover:text-foreground">
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
                {f.kind === "value" && sel.kind === "value" && (
                  <ValueFilterControl
                    filter={f}
                    values={sel.values}
                    onChange={(values) => onSelectionChange(f.id, { kind: "value", values })}
                    constraints={parentConstraints(f, filters, selections)}
                    enabled={!editing}
                  />
                )}
                {f.kind === "time" && sel.kind === "time" && (
                  <TimeFilterControl
                    value={sel.date_range}
                    onChange={(date_range) => onSelectionChange(f.id, { kind: "time", date_range })}
                    label={f.label ?? f.member}
                  />
                )}
                {f.kind === "numeric" && sel.kind === "numeric" && (
                  <NumericFilterControl
                    min={sel.min}
                    max={sel.max}
                    onChange={({ min, max }) => onSelectionChange(f.id, { kind: "numeric", min, max })}
                    label={f.label ?? f.member}
                  />
                )}
                {f.required && sel.kind === "value" && sel.values.length === 0 && (
                  <p className="text-xs text-amber-600">A selection is required.</p>
                )}
              </div>
            );
          })}

          <div className="flex flex-col gap-2 pt-2">
            {filters.length > 0 && (
              <Button variant="ghost" size="sm" onClick={onClearAll}>Clear all</Button>
            )}
            {editing && onAddFilter && (
              <Button variant="outline" size="sm" onClick={onAddFilter}>
                <Plus className="h-4 w-4" aria-hidden /> Add filter
              </Button>
            )}
          </div>
        </div>
      )}
    </aside>
  );
}
```

- [ ] **Step 6: Delete the old bar**

```bash
git rm frontend/src/components/dashboard/DashboardFilterBar.tsx frontend/src/test/dashboardFilterBar.test.tsx
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd frontend && pnpm exec vitest run src/test/dashboardFilterDrawer.test.tsx`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/dashboard/DashboardFilterDrawer.tsx frontend/src/components/dashboard/filterControls frontend/src/test/dashboardFilterDrawer.test.tsx
git commit -m "feat(dashboard): native-filter drawer + value/time/numeric controls (Slice C)"
```

---

## Task 8: Frontend — `NativeFilterEditor` dialog (add/edit/remove + scope + cascading config)

**Files:**
- Create: `frontend/src/components/dashboard/NativeFilterEditor.tsx`
- Test: `frontend/src/test/nativeFilterEditor.test.tsx` (create)

**Interfaces:**
- Consumes: `useSemanticModels`; `NativeFilter`, `DashboardTileRead`.
- Produces: `NativeFilterEditor({ open, onOpenChange, initial, existing, tiles, onSave, onRemove })` where `initial: NativeFilter | null` (null = add), `existing: NativeFilter[]` (for parent options + cycle guard), `tiles: DashboardTileRead[]` (scope picker), `onSave(f: NativeFilter)`, `onRemove?(id: string)`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/test/nativeFilterEditor.test.tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { NativeFilterEditor } from "@/components/dashboard/NativeFilterEditor";
import type { DashboardTileRead } from "@/types/api";

vi.mock("@/api/hooks", () => ({
  useSemanticModels: () => ({
    data: [{
      name: "regional_sales", title: "Regional Sales",
      measures: [{ name: "regional_sales.total_amount", title: "Total", type: "number" }],
      dimensions: [
        { name: "regional_sales.region", title: "Region", type: "string" },
        { name: "regional_sales.order_date", title: "Order Date", type: "time" },
      ],
    }],
  }),
}));

const tiles: DashboardTileRead[] = [];

describe("NativeFilterEditor", () => {
  it("saves a new value filter with member + label", () => {
    const onSave = vi.fn();
    render(<NativeFilterEditor open initial={null} existing={[]} tiles={tiles} onOpenChange={() => {}} onSave={onSave} />);
    fireEvent.change(screen.getByLabelText(/dimension/i), { target: { value: "regional_sales.region" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ kind: "value", member: "regional_sales.region" }));
  });

  it("offers only value filters as cascading parents", () => {
    render(
      <NativeFilterEditor
        open initial={null}
        existing={[
          { id: "v1", kind: "value", member: "regional_sales.region" },
          { id: "t1", kind: "time", member: "regional_sales.order_date" },
        ]}
        tiles={tiles} onOpenChange={() => {}} onSave={() => {}}
      />
    );
    const parent = screen.getByLabelText(/parent filter/i) as HTMLSelectElement;
    const optionValues = Array.from(parent.options).map((o) => o.value);
    expect(optionValues).toContain("v1");
    expect(optionValues).not.toContain("t1");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm exec vitest run src/test/nativeFilterEditor.test.tsx`
Expected: FAIL (component not found).

- [ ] **Step 3: Implement the editor**

```tsx
// frontend/src/components/dashboard/NativeFilterEditor.tsx
/**
 * NativeFilterEditor — add/edit a native filter (Slice C). Picks kind + governed
 * member, label, scope (auto / specific tiles), an optional cascading parent (value
 * filters only — the picker offers only value parents and excludes self), and required.
 */
import { useMemo, useState } from "react";

import { useSemanticModels } from "@/api/hooks";
import {
  Dialog, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import type { DashboardTileRead, NativeFilter, NativeFilterKind } from "@/types/api";

interface Props {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  initial: NativeFilter | null;
  existing: NativeFilter[];
  tiles: DashboardTileRead[];
  onSave: (f: NativeFilter) => void;
  onRemove?: (id: string) => void;
}

let _seq = 0;
const newId = () => `nf_${Date.now()}_${_seq++}`;

export function NativeFilterEditor({ open, onOpenChange, initial, existing, tiles, onSave, onRemove }: Props) {
  const { data: models } = useSemanticModels();
  const [kind, setKind] = useState<NativeFilterKind>(initial?.kind ?? "value");
  const [member, setMember] = useState(initial?.member ?? "");
  const [label, setLabel] = useState(initial?.label ?? "");
  const [parentId, setParentId] = useState(initial?.parent_id ?? "");
  const [scopeMode, setScopeMode] = useState(initial?.scope?.mode ?? "auto");
  const [tileIds, setTileIds] = useState<string[]>(initial?.scope?.tile_ids ?? []);
  const [required, setRequired] = useState(initial?.required ?? false);

  // Dimensions for value/time filters; measures+number dimensions for numeric.
  const memberOptions = useMemo(() => {
    const out: { value: string; label: string }[] = [];
    for (const m of models ?? []) {
      if (kind === "numeric") {
        for (const f of m.measures) out.push({ value: f.name, label: `${m.title} · ${f.title}` });
        for (const d of m.dimensions) if (d.type === "number") out.push({ value: d.name, label: `${m.title} · ${d.title}` });
      } else if (kind === "time") {
        for (const d of m.dimensions) if (d.type === "time") out.push({ value: d.name, label: `${m.title} · ${d.title}` });
      } else {
        for (const d of m.dimensions) out.push({ value: d.name, label: `${m.title} · ${d.title}` });
      }
    }
    return out;
  }, [models, kind]);

  const parentOptions = existing.filter((f) => f.kind === "value" && f.id !== initial?.id);

  function handleSave() {
    if (!member) return;
    const f: NativeFilter = {
      id: initial?.id ?? newId(),
      kind,
      member,
      label: label.trim() || null,
      operator: kind === "value" ? initial?.operator ?? "equals" : undefined,
      default_values: initial?.default_values ?? [],
      date_range: initial?.date_range ?? null,
      numeric_range: initial?.numeric_range ?? null,
      scope: { mode: scopeMode, tile_ids: scopeMode === "tiles" ? tileIds : [] },
      parent_id: kind === "value" && parentId ? parentId : null,
      required,
    };
    onSave(f);
    onOpenChange(false);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={initial ? "Edit filter" : "Add filter"}>
      <DialogHeader>
        <DialogTitle>{initial ? "Edit filter" : "Add filter"}</DialogTitle>
      </DialogHeader>

      <div className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="nf-kind">Kind</Label>
          <Select id="nf-kind" value={kind} onChange={(e) => { setKind(e.target.value as NativeFilterKind); setMember(""); }}>
            <option value="value">Value</option>
            <option value="time">Time range</option>
            <option value="numeric">Numeric range</option>
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="nf-member">Dimension</Label>
          <Select id="nf-member" value={member} onChange={(e) => setMember(e.target.value)}>
            <option value="">Choose…</option>
            {memberOptions.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="nf-label">Label (optional)</Label>
          <Input id="nf-label" value={label ?? ""} onChange={(e) => setLabel(e.target.value)} />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="nf-scope">Applies to</Label>
          <Select id="nf-scope" value={scopeMode} onChange={(e) => setScopeMode(e.target.value as "auto" | "tiles")}>
            <option value="auto">All compatible tiles</option>
            <option value="tiles">Specific tiles…</option>
          </Select>
          {scopeMode === "tiles" && (
            <div className="flex max-h-32 flex-col gap-1 overflow-auto rounded border p-2">
              {tiles.filter((t) => t.kind === "chart").map((t) => (
                <label key={t.id} className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={tileIds.includes(t.id)}
                    onChange={(e) => setTileIds(e.target.checked ? [...tileIds, t.id] : tileIds.filter((x) => x !== t.id))} />
                  {t.title ?? t.chart?.name ?? "Chart"}
                </label>
              ))}
            </div>
          )}
        </div>

        {kind === "value" && (
          <div className="space-y-1.5">
            <Label htmlFor="nf-parent">Parent filter (cascading, optional)</Label>
            <Select id="nf-parent" value={parentId ?? ""} onChange={(e) => setParentId(e.target.value)}>
              <option value="">None</option>
              {parentOptions.map((p) => (<option key={p.id} value={p.id}>{p.label ?? p.member}</option>))}
            </Select>
          </div>
        )}

        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={required} onChange={(e) => setRequired(e.target.checked)} /> Required
        </label>
      </div>

      <DialogFooter>
        {initial && onRemove && (
          <Button variant="ghost" className="text-destructive" onClick={() => { onRemove(initial.id); onOpenChange(false); }}>Remove</Button>
        )}
        <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
        <Button onClick={handleSave} disabled={!member}>Save</Button>
      </DialogFooter>
    </Dialog>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && pnpm exec vitest run src/test/nativeFilterEditor.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/dashboard/NativeFilterEditor.tsx frontend/src/test/nativeFilterEditor.test.tsx
git commit -m "feat(dashboard): native-filter editor dialog (kind/member/scope/cascading) (Slice C)"
```

---

## Task 9: Frontend — wire drawer + per-tile application into the dashboard

**Files:**
- Modify: `frontend/src/pages/DashboardDetail.tsx`
- Modify: `frontend/src/components/dashboard/DashboardGrid.tsx`
- Modify: `frontend/src/components/dashboard/DashboardCardTile.tsx`
- Test: `frontend/src/test/dashboardDetailFilters.test.tsx` (rewrite existing)

**Interfaces:**
- Consumes: `DashboardFilterDrawer` (Task 7), `NativeFilterEditor` (Task 8), `resolveTileFilters`/`FilterSelections`/`defaultSelection` (Task 5), `useChartData` override (Task 6), `useUpdateDashboard` with `native_filters`.
- Produces: `DashboardDetail` manages `native_filters` config (persisted) + live `selections` (session) + transient cross-filter overlay; `DashboardGrid` forwards `filters`, `selections`, `crossFilter`, `onCrossFilter`; `DashboardCardTile`/`ChartTileBody` resolve + apply per-tile.

- [ ] **Step 1: Rewrite the dashboard-filters integration test**

```tsx
// frontend/src/test/dashboardDetailFilters.test.tsx  (replace contents)
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { DashboardDetail } from "@/pages/DashboardDetail";

const board = {
  id: "d1", name: "Board", description: null, owner_id: null,
  created_at: "", updated_at: "",
  native_filters: [{ id: "f1", kind: "value", member: "regional_sales.region", operator: "equals", label: "Region" }],
  tiles: [{
    id: "t1", kind: "chart", chart_id: "c", content: null, title: "Sales", position: 0, x: 0, y: 0, w: 6, h: 4,
    chart: { id: "c", name: "Sales", source_kind: "semantic", source_ref: null, owner_id: null, created_at: "", updated_at: "",
      spec: { type: "bar", query: { metric_refs: ["regional_sales.total_amount"] }, encoding: { x: "regional_sales.region", series: [{ field: "regional_sales.total_amount" }] } } },
  }],
};

vi.mock("@/api/hooks", async () => {
  const actual = await vi.importActual<typeof import("@/api/hooks")>("@/api/hooks");
  return {
    ...actual,
    useDashboard: () => ({ data: board, isLoading: false, isError: false }),
    useUpdateDashboard: () => ({ mutate: vi.fn() }),
    useAddDashboardTile: () => ({ mutate: vi.fn() }),
    useSemanticValues: () => ({ data: { values: ["west", "east"] }, isLoading: false }),
    useDeleteDashboardTile: () => ({ mutate: vi.fn() }),
    useUpdateDashboardTile: () => ({ mutate: vi.fn() }),
  };
});
vi.mock("@/lib/identity", () => ({ useIdentity: () => ({ canEdit: true }) }));
vi.mock("@/lib/useChartData", () => ({ useChartData: () => ({ data: { columns: [], rows: [], row_count: 0 }, isLoading: false, isError: false }) }));

function wrap() {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/dashboards/d1"]}>
        <Routes><Route path="/dashboards/:dashboardId" element={<DashboardDetail />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("DashboardDetail native filters", () => {
  it("renders the native-filter drawer with the configured filter", () => {
    wrap();
    expect(screen.getByText("Region")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm exec vitest run src/test/dashboardDetailFilters.test.tsx`
Expected: FAIL (DashboardDetail still imports `DashboardFilterBar` / reads `board.filters`).

- [ ] **Step 3: Rewrite `DashboardDetail` filter state + layout**

In `frontend/src/pages/DashboardDetail.tsx`:
- Replace the `DashboardFilterBar` import with `DashboardFilterDrawer` and add `NativeFilterEditor`.
- Replace the single `activeFilter` state with native-filter state. Drop the `AddObjectDialog`'s `"filter"` kind option (remove the `<option value="filter">` and the filter branch in `buildContent`/validation).
- Replace the filter region:

```tsx
import { DashboardFilterDrawer } from "@/components/dashboard/DashboardFilterDrawer";
import { NativeFilterEditor } from "@/components/dashboard/NativeFilterEditor";
import { defaultSelection } from "@/lib/dashboardFilters";
import type { FilterSelection, FilterSelections } from "@/lib/dashboardFilters";
import type { NativeFilter, SemanticFilter } from "@/types/api";
```

Inside the component, replace `activeFilter`/`filterInitFor`/`handleFilterChange` with:

```tsx
  const filters: NativeFilter[] = board?.native_filters ?? [];
  const [selections, setSelections] = useState<FilterSelections>({});
  const [crossFilter, setCrossFilter] = useState<SemanticFilter | null>(null);
  const [editorFor, setEditorFor] = useState<{ open: boolean; id: string | null }>({ open: false, id: null });

  // Seed live selections from the persisted defaults once per dashboard (adjust-during-render).
  const [seedFor, setSeedFor] = useState<string | null>(null);
  if (board && seedFor !== board.id) {
    setSeedFor(board.id);
    const seeded: FilterSelections = {};
    for (const f of board.native_filters ?? []) seeded[f.id] = defaultSelection(f);
    setSelections(seeded);
    setCrossFilter(null);
  }

  function onSelectionChange(id: string, sel: FilterSelection) {
    setSelections((prev) => ({ ...prev, [id]: sel }));
  }
  function onClearAll() {
    const reset: FilterSelections = {};
    for (const f of filters) reset[f.id] = defaultSelection(f);
    setSelections(reset);
    setCrossFilter(null);
  }
  function persistFilters(next: NativeFilter[]) {
    if (board && canEdit) updateDashboard.mutate({ id: board.id, patch: { native_filters: next } });
  }
  function saveFilter(f: NativeFilter) {
    const next = filters.some((x) => x.id === f.id)
      ? filters.map((x) => (x.id === f.id ? f : x))
      : [...filters, f];
    persistFilters(next);
    setSelections((prev) => ({ ...prev, [f.id]: defaultSelection(f) }));
  }
  function removeFilter(id: string) {
    persistFilters(filters.filter((x) => x.id !== id));
  }
  /** Cross-filter: a clicked point becomes a transient session value overlay. */
  function handleCrossFilter(member: string, value: string) {
    setCrossFilter({ member, operator: "equals", values: [value] });
  }
```

Replace the body layout (the `board.tiles.length === 0 ? … : (<>…</>)` block) so the drawer sits beside the grid:

```tsx
        <div className="flex gap-4">
          {!editing || filters.length > 0 ? (
            <DashboardFilterDrawer
              filters={filters}
              selections={selections}
              onSelectionChange={onSelectionChange}
              onClearAll={onClearAll}
              editing={editing}
              onAddFilter={() => setEditorFor({ open: true, id: null })}
              onEditFilter={(id) => setEditorFor({ open: true, id })}
            />
          ) : null}
          <div className="min-w-0 flex-1">
            <DashboardGrid
              tiles={board.tiles}
              dashboardId={board.id}
              editing={editing}
              filters={filters}
              selections={selections}
              crossFilter={editing ? null : crossFilter}
              onCrossFilter={editing ? undefined : handleCrossFilter}
            />
          </div>
        </div>
```

Add the editor near the bottom (next to `AddObjectDialog`):

```tsx
      {editorFor.open && (
        <NativeFilterEditor
          open={editorFor.open}
          onOpenChange={(o) => setEditorFor((s) => ({ ...s, open: o }))}
          initial={editorFor.id ? filters.find((f) => f.id === editorFor.id) ?? null : null}
          existing={filters}
          tiles={board.tiles}
          onSave={saveFilter}
          onRemove={removeFilter}
        />
      )}
```

- [ ] **Step 4: Update `DashboardGrid` props**

In `frontend/src/components/dashboard/DashboardGrid.tsx`, replace the `activeFilter`/`onCrossFilter` props with `filters: NativeFilter[]`, `selections: FilterSelections`, `crossFilter: SemanticFilter | null`, `onCrossFilter?`, and forward them to each `DashboardCardTile`. (Mirror the existing prop-drilling; only the names change.)

- [ ] **Step 5: Update `DashboardCardTile` per-tile application**

In `frontend/src/components/dashboard/DashboardCardTile.tsx`:
- Replace the `activeFilter` props with `filters`, `selections`, `crossFilter`, `onCrossFilter`.
- Remove the `"filter"` case in `TileBody` and the `FilterSlicer` component and the `KIND_LABEL.filter` entry.
- Rewrite `ChartTileBody`'s filter computation to use the resolver:

```tsx
import { resolveTileFilters } from "@/lib/dashboardFilters";
import type { FilterSelections } from "@/lib/dashboardFilters";
import type { NativeFilter, SemanticFilter } from "@/types/api";
```

```tsx
  const { filters: resolved, dateRanges } = resolveTileFilters(filters, selections, tile);
  // Cross-filter overlays on top, only when its cube matches this tile.
  const tileCube = cubeOf((spec?.query.metric_refs ?? [])[0]);
  const crossApplies = !!crossFilter && !!tileCube && cubeOf(crossFilter.member) === tileCube;
  const appliedFilters: SemanticFilter[] = crossApplies ? [...resolved, crossFilter as SemanticFilter] : resolved;
  const hasOverride = Object.keys(dateRanges).length > 0;

  const { data, isLoading, isError } = useChartData(
    spec ?? null,
    appliedFilters.length > 0 ? appliedFilters : undefined,
    hasOverride ? dateRanges : undefined
  );
  const filterApplies = appliedFilters.length > 0 || hasOverride;
```

(The `crossDimension`/`onSelectCategory` wiring stays as-is.)

- [ ] **Step 6: Run the test + tsc + lint**

Run: `cd frontend && pnpm exec vitest run src/test/dashboardDetailFilters.test.tsx && pnpm exec tsc --noEmit && pnpm lint`
Expected: PASS; tsc clean (all `filters`→`native_filters` references resolved now).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/DashboardDetail.tsx frontend/src/components/dashboard/DashboardGrid.tsx frontend/src/components/dashboard/DashboardCardTile.tsx frontend/src/test/dashboardDetailFilters.test.tsx
git commit -m "feat(dashboard): wire native-filter drawer + per-tile scoping; cross-filter as session overlay (Slice C)"
```

---

## Task 10: Frontend — cascading verification (child options constrained by parent)

**Files:**
- Test: `frontend/src/test/cascadingFilters.test.tsx` (create)
- Modify (only if the test reveals a gap): `frontend/src/components/dashboard/DashboardFilterDrawer.tsx`

This task has **no new production code** if Tasks 7+9 are correct — `parentConstraints` already feeds the child's `useSemanticValues`. The task exists to lock the behaviour with a focused test (a reviewer could reject cascading independently).

- [ ] **Step 1: Write the test**

```tsx
// frontend/src/test/cascadingFilters.test.tsx
import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { DashboardFilterDrawer } from "@/components/dashboard/DashboardFilterDrawer";
import type { NativeFilter } from "@/types/api";

const calls: unknown[] = [];
vi.mock("@/api/hooks", () => ({
  useSemanticValues: (req: unknown) => { calls.push(req); return { data: { values: [] }, isLoading: false }; },
}));

const filters: NativeFilter[] = [
  { id: "country", kind: "value", member: "geo.country", operator: "equals" },
  { id: "city", kind: "value", member: "geo.city", operator: "equals", parent_id: "country" },
];

describe("cascading", () => {
  it("passes the parent selection as constraints on the child values request", () => {
    calls.length = 0;
    const qc = new QueryClient();
    render(
      <QueryClientProvider client={qc}>
        <DashboardFilterDrawer
          filters={filters}
          selections={{ country: { kind: "value", values: ["US"] }, city: { kind: "value", values: [] } }}
          onSelectionChange={() => {}} onClearAll={() => {}} editing={false}
        />
      </QueryClientProvider>
    );
    const childReq = calls.find((c) => (c as { member?: string })?.member === "geo.city") as { constraints?: unknown[] };
    expect(childReq?.constraints).toEqual([{ member: "geo.country", operator: "equals", values: ["US"] }]);
  });
});
```

- [ ] **Step 2: Run the test**

Run: `cd frontend && pnpm exec vitest run src/test/cascadingFilters.test.tsx`
Expected: PASS (if it fails, fix `parentConstraints` in `DashboardFilterDrawer.tsx` so the child request includes the parent constraint, then re-run).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/test/cascadingFilters.test.tsx
git commit -m "test(dashboard): lock cascading — child values constrained by parent selection (Slice C)"
```

---

## Task 11: Frontend — drill entries on the chart actions menu

**Files:**
- Modify: `frontend/src/components/chart/ChartActionsMenu.tsx`
- Test: `frontend/src/test/chartActionsDrill.test.tsx` (create)

**Interfaces:**
- Consumes: existing `ChartActionsMenu({ spec, data, chartHandle, title })`.
- Produces: two new optional props `onDrillBy?: () => void`, `onDrillToDetail?: () => void`; when provided, the menu shows **"Drill by…"** and **"Drill to detail…"** (only for semantic charts — `spec.query.metric_refs.length > 0` — and non-`number`/`table` types for drill-by).

> Note (refinement vs. spec wording): the drill *focus point* is chosen inside the drill modals from the chart's own x categories (Tasks 12–13), so no `ChartRenderer` click-hook change is needed. This keeps the renderer untouched while still scoping drill "to a point," as the spec intends.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/test/chartActionsDrill.test.tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { createRef } from "react";

import { ChartActionsMenu } from "@/components/chart/ChartActionsMenu";
import type { ChartRendererHandle } from "@/components/chart/ChartRenderer";
import type { ChartSpec, QueryResponse } from "@/types/api";

const spec: ChartSpec = {
  type: "bar", query: { metric_refs: ["regional_sales.total_amount"] },
  encoding: { x: "regional_sales.region", series: [{ field: "regional_sales.total_amount" }] },
};
const data: QueryResponse = { columns: ["regional_sales.region", "regional_sales.total_amount"], rows: [["west", 1]], row_count: 1 };

describe("ChartActionsMenu drill", () => {
  it("shows drill entries when handlers are provided and fires them", () => {
    const onDrillBy = vi.fn();
    const onDrillToDetail = vi.fn();
    const ref = createRef<ChartRendererHandle>();
    render(<ChartActionsMenu spec={spec} data={data} chartHandle={ref} title="C" onDrillBy={onDrillBy} onDrillToDetail={onDrillToDetail} />);
    fireEvent.click(screen.getByRole("button", { name: /chart actions|more/i }));
    fireEvent.click(screen.getByText(/drill by/i));
    expect(onDrillBy).toHaveBeenCalled();
  });
});
```

(Adjust the menu-trigger accessible name to match the existing button's `aria-label`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm exec vitest run src/test/chartActionsDrill.test.tsx`
Expected: FAIL (no drill entries).

- [ ] **Step 3: Add the entries**

In `ChartActionsMenu.tsx`: add `onDrillBy?: () => void` and `onDrillToDetail?: () => void` to the props. Compute `const isSemantic = (spec.query.metric_refs ?? []).length > 0;`. In the menu items list, before/after the existing items, add (matching the existing item markup):

```tsx
{isSemantic && onDrillBy && spec.type !== "number" && spec.type !== "table" && (
  <MenuItem onSelect={onDrillBy}>Drill by…</MenuItem>
)}
{isSemantic && onDrillToDetail && (
  <MenuItem onSelect={onDrillToDetail}>Drill to detail…</MenuItem>
)}
```

(Use whatever menu-item primitive the file already uses; keep styling identical.)

- [ ] **Step 4: Run test + tsc**

Run: `cd frontend && pnpm exec vitest run src/test/chartActionsDrill.test.tsx && pnpm exec tsc --noEmit`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/chart/ChartActionsMenu.tsx frontend/src/test/chartActionsDrill.test.tsx
git commit -m "feat(chart): drill-by / drill-to-detail entries on the chart actions menu (Slice C)"
```

---

## Task 12: Frontend — `DrillByModal` (grounded re-pivot)

**Files:**
- Create: `frontend/src/components/chart/DrillByModal.tsx`
- Test: `frontend/src/test/drillByModal.test.tsx` (create)

**Interfaces:**
- Consumes: `useSemanticModels`, `useChartData`, `ChartRenderer`; `buildDrillBySpec` helper (defined here and unit-tested).
- Produces:
  - `buildDrillBySpec(base: ChartSpec, dimension: string, point: { member: string; value: string } | null, extraFilters: SemanticFilter[]): ChartSpec`
  - `DrillByModal({ open, onOpenChange, spec, tileFilters, data })` where `tileFilters: SemanticFilter[]` are the active dashboard filters already scoped to this tile, and `data` provides the candidate focus points (the x column values).

- [ ] **Step 1: Write the failing test (pure builder first)**

```tsx
// frontend/src/test/drillByModal.test.tsx
import { describe, expect, it } from "vitest";

import { buildDrillBySpec } from "@/components/chart/DrillByModal";
import type { ChartSpec } from "@/types/api";

const base: ChartSpec = {
  type: "bar", query: { metric_refs: ["regional_sales.total_amount"] },
  encoding: { x: "regional_sales.region", series: [{ field: "regional_sales.total_amount" }] },
};

describe("buildDrillBySpec", () => {
  it("re-groups by the chosen dimension and filters to the focus point", () => {
    const out = buildDrillBySpec(base, "regional_sales.product", { member: "regional_sales.region", value: "west" }, []);
    expect(out.query.metric_refs).toEqual(["regional_sales.total_amount"]);
    expect(out.query.dimensions).toEqual(["regional_sales.product"]);
    expect(out.encoding.x).toBe("regional_sales.product");
    expect(out.query.filters).toContainEqual({ member: "regional_sales.region", operator: "equals", values: ["west"] });
  });

  it("merges active tile filters and omits the point filter when no point is focused", () => {
    const out = buildDrillBySpec(base, "regional_sales.product", null, [{ member: "regional_sales.region", operator: "equals", values: ["east"] }]);
    expect(out.query.filters).toEqual([{ member: "regional_sales.region", operator: "equals", values: ["east"] }]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm exec vitest run src/test/drillByModal.test.tsx`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement the modal + builder**

```tsx
// frontend/src/components/chart/DrillByModal.tsx
/**
 * DrillByModal — pivot a chart by another governed dimension of the same cube,
 * optionally focused on one point. Runs a grounded /semantic/query via useChartData
 * (no backend change) and renders the result with the shared ChartRenderer.
 */
import { useMemo, useState } from "react";

import { useSemanticModels } from "@/api/hooks";
import { useChartData } from "@/lib/useChartData";
import { ChartRenderer } from "@/components/chart/ChartRenderer";
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select } from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/ui/spinner";
import { EmptyState } from "@/components/ui/empty-state";
import { cubeOf } from "@/lib/dashboardFilters";
import type { ChartSpec, QueryResponse, SemanticFilter } from "@/types/api";

export function buildDrillBySpec(
  base: ChartSpec,
  dimension: string,
  point: { member: string; value: string } | null,
  extraFilters: SemanticFilter[]
): ChartSpec {
  const pointFilter: SemanticFilter[] = point
    ? [{ member: point.member, operator: "equals", values: [point.value] }]
    : [];
  return {
    ...base,
    type: base.type === "number" || base.type === "table" ? "bar" : base.type,
    query: {
      ...base.query,
      dimensions: [dimension],
      time_dimensions: [],
      filters: [...(base.query.filters ?? []), ...extraFilters, ...pointFilter],
    },
    encoding: { x: dimension, series: base.encoding.series, breakdown: [] },
  };
}

interface Props {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  spec: ChartSpec;
  tileFilters: SemanticFilter[];
  data: QueryResponse;
}

export function DrillByModal({ open, onOpenChange, spec, tileFilters, data }: Props) {
  const { data: models } = useSemanticModels();
  const baseCube = cubeOf((spec.query.metric_refs ?? [])[0]);
  const baseX = spec.encoding.x;

  // Other governed dimensions on the same cube (excluding the current x).
  const dimensionOptions = useMemo(() => {
    const model = (models ?? []).find((m) => m.name === baseCube);
    return (model?.dimensions ?? []).filter((d) => d.name !== baseX);
  }, [models, baseCube, baseX]);

  const [dimension, setDimension] = useState("");
  const [focus, setFocus] = useState(""); // "" = all points

  // Candidate focus points = distinct x-column values present in the tile's data.
  const xIndex = baseX ? data.columns.indexOf(baseX) : -1;
  const points = xIndex >= 0 ? Array.from(new Set(data.rows.map((r) => String(r[xIndex])))) : [];

  const derived = dimension
    ? buildDrillBySpec(spec, dimension, focus && baseX ? { member: baseX, value: focus } : null, tileFilters)
    : null;
  const { data: result, isLoading } = useChartData(derived);

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Drill by">
      <DialogHeader><DialogTitle>Drill by</DialogTitle></DialogHeader>
      <div className="space-y-3">
        <div className="flex gap-3">
          <div className="flex-1 space-y-1">
            <Label htmlFor="drill-dim">Dimension</Label>
            <Select id="drill-dim" value={dimension} onChange={(e) => setDimension(e.target.value)}>
              <option value="">Choose…</option>
              {dimensionOptions.map((d) => (<option key={d.name} value={d.name}>{d.title}</option>))}
            </Select>
          </div>
          {points.length > 0 && (
            <div className="flex-1 space-y-1">
              <Label htmlFor="drill-focus">Focus ({baseX})</Label>
              <Select id="drill-focus" value={focus} onChange={(e) => setFocus(e.target.value)}>
                <option value="">All</option>
                {points.map((p) => (<option key={p} value={p}>{p}</option>))}
              </Select>
            </div>
          )}
        </div>
        <div className="h-72">
          {!derived ? (
            <EmptyState title="Pick a dimension" description="Choose a dimension to drill by." />
          ) : isLoading ? (
            <div className="flex h-full items-center justify-center"><Spinner label="Loading" /></div>
          ) : result && result.row_count > 0 ? (
            <ChartRenderer spec={derived} data={result} title="Drill by" className="h-72" />
          ) : (
            <EmptyState title="No data" description="This drill returned no rows." />
          )}
        </div>
      </div>
    </Dialog>
  );
}
```

- [ ] **Step 4: Run tests + tsc**

Run: `cd frontend && pnpm exec vitest run src/test/drillByModal.test.tsx && pnpm exec tsc --noEmit`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/chart/DrillByModal.tsx frontend/src/test/drillByModal.test.tsx
git commit -m "feat(chart): grounded drill-by modal (re-pivot by a governed dimension) (Slice C)"
```

---

## Task 13: Frontend — `DrillToDetailModal` (grounded breakdown table) + wire drill into tiles

**Files:**
- Create: `frontend/src/components/chart/DrillToDetailModal.tsx`
- Modify: `frontend/src/components/dashboard/DashboardCardTile.tsx` (wire `onDrillBy`/`onDrillToDetail` to open the modals)
- Test: `frontend/src/test/drillToDetailModal.test.tsx` (create)

**Interfaces:**
- Consumes: `useSemanticModels`, `useSemanticQuery`, `TableRenderer` (confirm export at `@/components/chart/TableRenderer`); `buildDetailRequest` helper.
- Produces:
  - `buildDetailRequest(spec: ChartSpec, models: SemanticModelRead[], point: { member: string; value: string } | null, extraFilters: SemanticFilter[]): SemanticQueryRequest | null` — measures = spec metrics; dimensions = the cube's governed dimensions **not already encoded**; filters = spec + extra + point.
  - `DrillToDetailModal({ open, onOpenChange, spec, tileFilters, data })`.

- [ ] **Step 1: Write the failing test (builder)**

```tsx
// frontend/src/test/drillToDetailModal.test.tsx
import { describe, expect, it } from "vitest";

import { buildDetailRequest } from "@/components/chart/DrillToDetailModal";
import type { ChartSpec, SemanticModelRead } from "@/types/api";

const spec: ChartSpec = {
  type: "bar", query: { metric_refs: ["regional_sales.total_amount"], dimensions: ["regional_sales.region"] },
  encoding: { x: "regional_sales.region", series: [{ field: "regional_sales.total_amount" }] },
};
const models: SemanticModelRead[] = [{
  name: "regional_sales", title: "Regional Sales",
  measures: [{ name: "regional_sales.total_amount", title: "Total", type: "number" }],
  dimensions: [
    { name: "regional_sales.region", title: "Region", type: "string" },
    { name: "regional_sales.product", title: "Product", type: "string" },
  ],
}];

describe("buildDetailRequest", () => {
  it("breaks the metric down by the remaining governed dimensions, filtered to the point", () => {
    const req = buildDetailRequest(spec, models, { member: "regional_sales.region", value: "west" }, []);
    expect(req?.measures).toEqual(["regional_sales.total_amount"]);
    expect(req?.dimensions).toEqual(["regional_sales.product"]); // region already encoded → excluded
    expect(req?.filters).toContainEqual({ member: "regional_sales.region", operator: "equals", values: ["west"] });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm exec vitest run src/test/drillToDetailModal.test.tsx`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement the modal + builder**

```tsx
// frontend/src/components/chart/DrillToDetailModal.tsx
/**
 * DrillToDetailModal — a grounded detail breakdown of a clicked point (Slice C).
 * Golden rule #3: NOT raw rows — it re-queries the semantic layer for the metric(s)
 * broken down by the cube's remaining governed dimensions, filtered to the point.
 */
import { useMemo, useState } from "react";

import { useSemanticModels, useSemanticQuery } from "@/api/hooks";
import { TableRenderer } from "@/components/chart/TableRenderer";
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select } from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/ui/spinner";
import { EmptyState } from "@/components/ui/empty-state";
import { cubeOf } from "@/lib/dashboardFilters";
import type { ChartSpec, QueryResponse, SemanticFilter, SemanticModelRead, SemanticQueryRequest } from "@/types/api";

export function buildDetailRequest(
  spec: ChartSpec,
  models: SemanticModelRead[],
  point: { member: string; value: string } | null,
  extraFilters: SemanticFilter[]
): SemanticQueryRequest | null {
  const cube = cubeOf((spec.query.metric_refs ?? [])[0]);
  const model = models.find((m) => m.name === cube);
  const measures = spec.query.metric_refs ?? [];
  if (!model || measures.length === 0) return null;
  const encoded = new Set<string>([
    ...(spec.query.dimensions ?? []),
    ...(spec.encoding.x ? [spec.encoding.x] : []),
  ]);
  const dimensions = model.dimensions.map((d) => d.name).filter((n) => !encoded.has(n));
  const pointFilter: SemanticFilter[] = point
    ? [{ member: point.member, operator: "equals", values: [point.value] }]
    : [];
  return {
    measures,
    dimensions,
    filters: [...(spec.query.filters ?? []), ...extraFilters, ...pointFilter],
  };
}

interface Props {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  spec: ChartSpec;
  tileFilters: SemanticFilter[];
  data: QueryResponse;
}

export function DrillToDetailModal({ open, onOpenChange, spec, tileFilters, data }: Props) {
  const { data: models } = useSemanticModels();
  const baseX = spec.encoding.x;
  const xIndex = baseX ? data.columns.indexOf(baseX) : -1;
  const points = xIndex >= 0 ? Array.from(new Set(data.rows.map((r) => String(r[xIndex])))) : [];
  const [focus, setFocus] = useState("");

  const req = useMemo(
    () => buildDetailRequest(spec, models ?? [], focus && baseX ? { member: baseX, value: focus } : null, tileFilters),
    [spec, models, focus, baseX, tileFilters]
  );
  const { data: result, isLoading } = useSemanticQuery(open ? req : null);

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Drill to detail">
      <DialogHeader><DialogTitle>Drill to detail</DialogTitle></DialogHeader>
      <div className="space-y-3">
        {points.length > 0 && (
          <div className="space-y-1">
            <Label htmlFor="detail-focus">Focus ({baseX})</Label>
            <Select id="detail-focus" value={focus} onChange={(e) => setFocus(e.target.value)}>
              <option value="">All</option>
              {points.map((p) => (<option key={p} value={p}>{p}</option>))}
            </Select>
          </div>
        )}
        <div className="max-h-96 overflow-auto">
          {isLoading ? (
            <div className="flex h-40 items-center justify-center"><Spinner label="Loading detail" /></div>
          ) : result && result.row_count > 0 ? (
            <TableRenderer data={result} />
          ) : (
            <EmptyState title="No detail" description="This breakdown returned no rows." />
          )}
        </div>
      </div>
    </Dialog>
  );
}
```

> If `TableRenderer`'s actual prop name differs (e.g. it takes `columns`/`rows` rather than `data`), adapt the call to its real signature — confirm by opening `frontend/src/components/chart/TableRenderer.tsx` first.

- [ ] **Step 4: Wire the modals into the tile**

In `DashboardCardTile.tsx` `ChartTileBody`, add modal state and pass handlers to `ChartActionsMenu`:

```tsx
import { DrillByModal } from "@/components/chart/DrillByModal";
import { DrillToDetailModal } from "@/components/chart/DrillToDetailModal";
```

```tsx
  const [drillBy, setDrillBy] = useState(false);
  const [drillDetail, setDrillDetail] = useState(false);
  const isSemantic = (spec?.query.metric_refs ?? []).length > 0;
```

In the `ChartActionsMenu` usage add:

```tsx
            <ChartActionsMenu
              spec={spec} data={data} chartHandle={chartHandle} title={title}
              onDrillBy={isSemantic ? () => setDrillBy(true) : undefined}
              onDrillToDetail={isSemantic ? () => setDrillDetail(true) : undefined}
            />
```

After the `ChartRenderer`, render the modals (only when data is present):

```tsx
          {drillBy && (
            <DrillByModal open={drillBy} onOpenChange={setDrillBy} spec={spec} tileFilters={appliedFilters} data={data} />
          )}
          {drillDetail && (
            <DrillToDetailModal open={drillDetail} onOpenChange={setDrillDetail} spec={spec} tileFilters={appliedFilters} data={data} />
          )}
```

- [ ] **Step 5: Run tests + tsc + lint + full frontend suite**

Run: `cd frontend && pnpm exec vitest run src/test/drillToDetailModal.test.tsx && pnpm test && pnpm exec tsc --noEmit && pnpm lint`
Expected: PASS across the suite.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/chart/DrillToDetailModal.tsx frontend/src/components/dashboard/DashboardCardTile.tsx frontend/src/test/drillToDetailModal.test.tsx
git commit -m "feat(chart): grounded drill-to-detail modal + wire drill into dashboard tiles (Slice C)"
```

---

## Task 14: Docs

**Files:**
- Modify/create: `docs/DASHBOARDS.md` (or the existing dashboards page if differently named — confirm with a quick search)

- [ ] **Step 1: Find the docs page**

Run: `ls docs | grep -i dash` (or search for an existing dashboards doc). If none exists, create `docs/DASHBOARDS.md`.

- [ ] **Step 2: Write the native-filters section**

Document, with examples:
- The three filter kinds (value/time/numeric) and how each resolves to semantic primitives.
- The `native_filters` config shape on the dashboard, and that the live selection is session state seeded from each filter's persisted default.
- Per-tile scoping (auto vs specific tiles) and the cube-compatibility safety rule.
- Cascading (parent → child constraints) and the cycle/parent-must-be-value rules.
- Drill-by and drill-to-detail (grounded; drill-to-detail is a semantic breakdown, never raw rows — golden rule #3).
- The grounded `POST /semantic/values` endpoint (member/search/constraints/limit; cap = `max_filter_values`).
- A migration note: the single-filter bar and the `filter` decoration tile were **removed** (fresh-start, no data migration).

- [ ] **Step 3: Commit**

```bash
git add docs/DASHBOARDS.md
git commit -m "docs(dashboard): native filters, scoping, cascading, drill (Slice C)"
```

---

## Final verification

- [ ] Backend: `cd backend && .venv/Scripts/python.exe -m pytest && .venv/Scripts/ruff.exe check . && .venv/Scripts/mypy.exe app` → all green.
- [ ] Frontend: `cd frontend && pnpm test && pnpm exec tsc --noEmit && pnpm lint` → all green.
- [ ] Manual smoke (optional, via `/run` or the local stack): add a value filter on a dashboard, confirm the drawer fetches values, scope it to one tile, add a cascading child, and drill by/into a point.

---

## Self-Review

**Spec coverage** (spec §1–10 → tasks):
- §1 data model → Task 1. §2 dashboard schema → Tasks 1–2. §3 `/semantic/values` → Task 3. §4 type mirror → Task 4. §5 filter drawer → Task 7. §6 per-tile application → Tasks 5, 9. §7 cascading → Tasks 7, 10. §8 drill-by → Tasks 11–12. §9 drill-to-detail → Tasks 11, 13. §10 compliance → enforced in Tasks 1/3 (validation) + 12/13 (grounded re-query). Testing/Docs → each task + Task 14. **No gaps.**

**Type consistency:** `resolveTileFilters`/`filterAppliesToTile`/`defaultSelection`/`cubeOf` (Task 5) are used verbatim in Tasks 7/9/12/13. `buildSemanticRequest(spec, viewFilters?, dateRangeOverrides?)` (Task 6) matches the `useChartData(spec, filters?, dateRangeOverrides?)` call in Task 9. `NativeFilter`/`FilterScope`/`NumericRange` field names match across backend (Task 1) and TS mirror (Task 4). `SemanticValuesRequest` fields (member/search/constraints/limit) match across Tasks 3–4 and the cascading test (Task 10).

**Known confirmations for the implementer (verify before/while coding, not blockers):**
1. `TableRenderer` export + prop shape (`@/components/chart/TableRenderer`) — confirm in Task 13.
2. `ChartActionsMenu` menu-item primitive + trigger `aria-label` — match existing markup in Task 11.
3. The existing dashboard API tests asserting `filters` must be migrated to `native_filters` (Task 2, Step 7).
4. `Dialog` usage passes both a `title` prop and a `DialogTitle` child in this codebase (see `AddObjectDialog`) — mirror that.

**Placeholder scan:** no TBD/TODO; every code step shows real code; every test step shows real assertions.
