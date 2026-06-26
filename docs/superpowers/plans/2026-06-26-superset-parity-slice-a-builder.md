# Superset-parity Slice A (Chart-builder query shaping) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the chart builder Superset-Explore parity on query shaping (time-range filtering, per-chart filters, row limit, server sort) and chart actions (view as table / view query / download CSV+PNG), all persisted on `ChartSpec` so saved charts and dashboard tiles reproduce it.

**Architecture:** Additive, no breaking change (spec stays `version "1"`). Backend already accepts `filters`/`order`/`limit` on `SemanticQueryRequest`; we add `date_range` to the time dimension and let `ChartQuery` carry `filters`/`order`/`limit`. The frontend builder writes them onto the spec; the existing `useChartData` hook forwards them through one shared `ChartQuery → SemanticQueryRequest` mapper, so dashboards and AI charts benefit for free.

**Tech Stack:** Backend — Python 3.12, FastAPI, Pydantic v2, pytest. Frontend — React + TS, Vite, TanStack Query, ECharts, dnd-kit, Vitest + RTL.

## Global Constraints

- **No hardcoded config** (golden rule #1): row limit is clamped to `settings.max_query_rows`; relative date-range tokens are a closed set; nothing tenant- or environment-specific is literal.
- **Tenant context is server-resolved** (golden rule #2): never read a tenant id from the client; all Cube calls already take `TenantContext`.
- **Grounded & read-only** (golden rule #3): every filter member and order key is re-validated against the governed Cube allow-list server-side; "View query" surfaces the **semantic** query only, never SQL.
- **Definition of done** (golden rule #5): each task ends green on its tests; the whole slice ends with `cd backend && uv run pytest && uv run ruff check . && uv run mypy app` and `cd frontend && pnpm test && pnpm exec tsc --noEmit && pnpm lint` all passing, and `docs/CHART_SPEC.md` updated.
- The frontend `types/api.ts` mirrors the backend schemas **field-for-field in snake_case**.
- Run backend tools via `backend/.venv/Scripts/<tool>.exe` if `uv` is unavailable (see project memory `toolchain-shell-access`).

---

### Task 1: Backend — `date_range` on `SemanticTimeDimension`

**Files:**
- Modify: `backend/app/schemas/semantic.py`
- Test: `backend/tests/test_semantic_date_range.py` (create)

**Interfaces:**
- Produces: `SemanticTimeDimension.date_range: RelativeDateRange | list[str] | None`; a read-only property `SemanticTimeDimension.cube_date_range -> str | list[str] | None` returning the Cube-native value (relative token → Cube string, absolute pair passed through, `None` when unset). Module constant `RelativeDateRange` (a `Literal`) and `_RELATIVE_TO_CUBE: dict[str, str]`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_semantic_date_range.py`:

```python
"""Time-range (date_range) support on SemanticTimeDimension (Slice A)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.semantic import SemanticTimeDimension


def test_relative_token_maps_to_cube_string() -> None:
    td = SemanticTimeDimension(dimension="s.created", granularity="month", date_range="last_30_days")
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_semantic_date_range.py -v`
Expected: FAIL — `TypeError`/`ValidationError` because `date_range` is not a field yet.

- [ ] **Step 3: Implement in `backend/app/schemas/semantic.py`**

Add after the `SemanticGranularity` definition (around line 60):

```python
# Relative date-range tokens (closed set) → Cube's native relative range strings.
RelativeDateRange = Literal[
    "last_7_days",
    "last_30_days",
    "last_90_days",
    "this_month",
    "last_month",
    "this_quarter",
    "last_quarter",
    "this_year",
    "last_year",
]

_RELATIVE_TO_CUBE: dict[str, str] = {
    "last_7_days": "last 7 days",
    "last_30_days": "last 30 days",
    "last_90_days": "last 90 days",
    "this_month": "this month",
    "last_month": "last month",
    "this_quarter": "this quarter",
    "last_quarter": "last quarter",
    "this_year": "this year",
    "last_year": "last year",
}
```

Add `date_range` to `SemanticTimeDimension` (after the `granularity` field) and a validator + property. Add `from datetime import date` to the imports at the top of the file:

```python
    # Optional time-range filter. Either a relative token (closed set) or an absolute
    # [from, to] pair of ISO dates. Maps to Cube's ``dateRange`` (see cube_date_range).
    date_range: RelativeDateRange | list[str] | None = None

    @model_validator(mode="after")
    def _validate_absolute_range(self) -> SemanticTimeDimension:
        if isinstance(self.date_range, list):
            if len(self.date_range) != 2:
                raise ValueError("an absolute date_range must be exactly two ISO dates")
            try:
                start, end = (date.fromisoformat(d) for d in self.date_range)
            except ValueError as exc:
                raise ValueError("date_range entries must be ISO dates (YYYY-MM-DD)") from exc
            if start > end:
                raise ValueError("date_range start must not be after end")
        return self

    @property
    def cube_date_range(self) -> str | list[str] | None:
        """The Cube-native dateRange value (None when unset)."""
        if self.date_range is None:
            return None
        if isinstance(self.date_range, list):
            return list(self.date_range)
        return _RELATIVE_TO_CUBE[self.date_range]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_semantic_date_range.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/semantic.py backend/tests/test_semantic_date_range.py
git commit -m "feat(semantic): add date_range to SemanticTimeDimension (Slice A)"
```

---

### Task 2: Backend — service forwards `dateRange` to Cube

**Files:**
- Modify: `backend/app/services/semantic.py:91-96` (the `cube_time_dims` construction)
- Test: `backend/tests/test_semantic_api.py` (add two tests)

**Interfaces:**
- Consumes: `SemanticTimeDimension.cube_date_range` (Task 1).
- Produces: each Cube time-dimension dict now includes `"dateRange"` when set.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_semantic_api.py`:

```python
@pytest.mark.asyncio
async def test_query_forwards_relative_date_range_to_cube(
    client_with_db: TestClient, make_tenant: Any, fake_cube: _FakeCube
) -> None:
    await make_tenant("local")
    resp = client_with_db.post(
        "/api/v1/semantic/query",
        headers=_auth(),
        json={
            "measures": ["regional_sales.total_amount"],
            "time_dimensions": [
                {
                    "dimension": "regional_sales.region",
                    "granularity": "month",
                    "date_range": "last_30_days",
                }
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    assert fake_cube.seen_time_dims[-1] == [
        {
            "dimension": "regional_sales.region",
            "granularity": "month",
            "dateRange": "last 30 days",
        }
    ]


@pytest.mark.asyncio
async def test_query_forwards_absolute_date_range_to_cube(
    client_with_db: TestClient, make_tenant: Any, fake_cube: _FakeCube
) -> None:
    await make_tenant("local")
    resp = client_with_db.post(
        "/api/v1/semantic/query",
        headers=_auth(),
        json={
            "measures": ["regional_sales.total_amount"],
            "time_dimensions": [
                {
                    "dimension": "regional_sales.region",
                    "granularity": "day",
                    "date_range": ["2024-01-01", "2024-03-31"],
                }
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    assert fake_cube.seen_time_dims[-1] == [
        {
            "dimension": "regional_sales.region",
            "granularity": "day",
            "dateRange": ["2024-01-01", "2024-03-31"],
        }
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_semantic_api.py -k date_range -v`
Expected: FAIL — `seen_time_dims` has no `dateRange` key.

- [ ] **Step 3: Implement — replace the `cube_time_dims` comprehension**

In `backend/app/services/semantic.py`, replace lines 91-96:

```python
        cube_time_dims = [
            {"dimension": td.dimension}
            if td.granularity is None
            else {"dimension": td.dimension, "granularity": td.granularity}
            for td in req.time_dimensions
        ]
```

with:

```python
        cube_time_dims: list[dict[str, Any]] = []
        for td in req.time_dimensions:
            entry: dict[str, Any] = {"dimension": td.dimension}
            if td.granularity is not None:
                entry["granularity"] = td.granularity
            if td.cube_date_range is not None:
                entry["dateRange"] = td.cube_date_range
            cube_time_dims.append(entry)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_semantic_api.py -v`
Expected: PASS (all, including the two new tests and the existing time-dim/filter tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/semantic.py backend/tests/test_semantic_api.py
git commit -m "feat(semantic): forward time-dimension dateRange to Cube (Slice A)"
```

---

### Task 3: Backend — `ChartQuery` carries `filters` / `order` / `limit`

**Files:**
- Modify: `backend/app/schemas/chart.py` (imports + `ChartQuery`)
- Modify: `docs/examples/chart-spec.example.json`
- Modify: `docs/CHART_SPEC.md`
- Test: `backend/tests/test_chart_spec.py` (add tests)

**Interfaces:**
- Consumes: `SemanticFilter`, `SemanticRef`, `OrderDir` from `app.schemas.semantic`.
- Produces: `ChartQuery.filters: list[SemanticFilter]`, `ChartQuery.order: dict[str, str]`, `ChartQuery.limit: int | None`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_chart_spec.py`:

```python
def test_chart_query_carries_filters_order_limit() -> None:
    spec = ChartSpec.model_validate(
        {
            "type": "bar",
            "query": {
                "metric_refs": ["sales.total"],
                "dimensions": ["sales.region"],
                "filters": [
                    {"member": "sales.region", "operator": "equals", "values": ["west"]}
                ],
                "order": {"sales.total": "desc"},
                "limit": 25,
            },
            "encoding": {"x": "sales.region", "series": [{"field": "sales.total"}]},
        }
    )
    assert spec.query.filters[0].member == "sales.region"
    assert spec.query.order == {"sales.total": "desc"}
    assert spec.query.limit == 25


def test_chart_query_defaults_are_empty() -> None:
    spec = ChartSpec.model_validate(
        {
            "type": "bar",
            "query": {"metric_refs": ["sales.total"]},
            "encoding": {"x": "sales.region", "series": [{"field": "sales.total"}]},
        }
    )
    assert spec.query.filters == []
    assert spec.query.order == {}
    assert spec.query.limit is None


def test_chart_query_time_dimension_date_range_round_trips() -> None:
    spec = ChartSpec.model_validate(
        {
            "type": "line",
            "query": {
                "metric_refs": ["sales.total"],
                "time_dimensions": [
                    {"dimension": "sales.created", "granularity": "month", "date_range": "last_90_days"}
                ],
            },
            "encoding": {"x": "sales.created.month", "series": [{"field": "sales.total"}]},
        }
    )
    assert spec.query.time_dimensions[0].cube_date_range == "last 90 days"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_chart_spec.py -k "filters_order_limit or defaults_are_empty" -v`
Expected: FAIL — `ChartQuery` has no `filters`/`order`/`limit`.

- [ ] **Step 3: Implement in `backend/app/schemas/chart.py`**

Update the import on line 33:

```python
from app.schemas.semantic import OrderDir, SemanticFilter, SemanticRef, SemanticTimeDimension
```

Add to `ChartQuery` after the `time_dimensions` field (after line 99):

```python
    # Optional governed filters carried on the spec so a saved chart re-runs with the
    # same constraints. Each member is re-validated against the governed allow-list by
    # the semantic service before any Cube call (golden rule #3).
    filters: list[SemanticFilter] = Field(default_factory=list)
    # Optional server-side ordering, e.g. {"sales.total": "desc"}. Keys must be members
    # selected by this query; the service rejects anything else.
    order: dict[SemanticRef, OrderDir] = Field(default_factory=dict)
    # Optional per-chart row cap; the service clamps it to settings.max_query_rows.
    limit: int | None = Field(default=None, ge=1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_chart_spec.py -k "filters_order_limit or defaults_are_empty or date_range" -v`
Expected: PASS.

- [ ] **Step 5: Update the canonical fixture so the round-trip test stays green**

`model_dump()` now emits the three new keys, so the fixture must include them. In `docs/examples/chart-spec.example.json`, change the `query` object (lines 4-18) to add the new fields after `"time_dimensions": []`:

```json
  "query": {
    "dataset_id": "3f8c8b1e-7c2a-4e5d-9a1b-2c3d4e5f6a7b",
    "query": {
      "dimensions": ["month"],
      "metrics": [
        { "function": "sum", "column": "sales", "alias": "sales" },
        { "function": "sum", "column": "returns", "alias": "returns" }
      ],
      "filters": [],
      "limit": 50
    },
    "metric_refs": [],
    "dimensions": [],
    "time_dimensions": [],
    "filters": [],
    "order": {},
    "limit": null
  },
```

- [ ] **Step 6: Run the full chart-spec suite (round-trip included)**

Run: `cd backend && uv run pytest tests/test_chart_spec.py -v`
Expected: PASS (including `test_canonical_fixture_round_trips`).

- [ ] **Step 7: Document in `docs/CHART_SPEC.md`**

Add a short subsection under the `ChartQuery` description documenting the three new optional fields and that `time_dimensions[].date_range` accepts a relative token (`last_7_days`, `last_30_days`, `last_90_days`, `this_month`, `last_month`, `this_quarter`, `last_quarter`, `this_year`, `last_year`) or an absolute `[from, to]` ISO-date pair. Note they are validated against the governed allow-list and clamped server-side.

- [ ] **Step 8: Commit**

```bash
git add backend/app/schemas/chart.py backend/tests/test_chart_spec.py docs/examples/chart-spec.example.json docs/CHART_SPEC.md
git commit -m "feat(chart): persist filters/order/limit on ChartQuery (Slice A)"
```

---

### Task 4: Frontend — mirror the new types

**Files:**
- Modify: `frontend/src/types/api.ts` (`SemanticTimeDimension`, `ChartQuery`, add `RelativeDateRange`)
- Test: `frontend/src/test/chartSpec.test.ts` (add a type-level assignability check)

**Interfaces:**
- Produces: TS `RelativeDateRange`; `SemanticTimeDimension.date_range?`; `ChartQuery.filters?` / `order?` / `limit?`.

- [ ] **Step 1: Implement the type mirror in `frontend/src/types/api.ts`**

Add above `SemanticTimeDimension` (before line 258):

```typescript
/** Relative time-range tokens (mirrors schemas/semantic.py RelativeDateRange). */
export type RelativeDateRange =
  | "last_7_days"
  | "last_30_days"
  | "last_90_days"
  | "this_month"
  | "last_month"
  | "this_quarter"
  | "last_quarter"
  | "this_year"
  | "last_year";
```

Add to `SemanticTimeDimension` (after `granularity`):

```typescript
  /** Time-range filter: a relative token or an absolute [from, to] ISO-date pair. */
  date_range?: RelativeDateRange | string[] | null;
```

Add to `ChartQuery` (after `time_dimensions`, around line 105):

```typescript
  /** Governed filters carried on the spec; re-validated server-side. */
  filters?: SemanticFilter[];
  /** Server-side ordering, e.g. { "sales.total": "desc" }. */
  order?: Record<string, "asc" | "desc">;
  /** Per-chart row cap; clamped server-side. */
  limit?: number | null;
```

`SemanticFilter` is declared later in the file but TS interface ordering does not matter.

- [ ] **Step 2: Write the assignability test**

Append to `frontend/src/test/chartSpec.test.ts`:

```typescript
import type { ChartQuery, RelativeDateRange } from "@/types/api";

test("ChartQuery accepts filters/order/limit and time date_range", () => {
  const range: RelativeDateRange = "last_30_days";
  const q: ChartQuery = {
    metric_refs: ["sales.total"],
    dimensions: ["sales.region"],
    time_dimensions: [{ dimension: "sales.created", granularity: "month", date_range: range }],
    filters: [{ member: "sales.region", operator: "equals", values: ["west"] }],
    order: { "sales.total": "desc" },
    limit: 25,
  };
  expect(q.limit).toBe(25);
  expect(q.order?.["sales.total"]).toBe("desc");
});
```

- [ ] **Step 3: Run the test + typecheck**

Run: `cd frontend && pnpm exec tsc --noEmit && pnpm test -- chartSpec`
Expected: typecheck clean; test PASSES.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/api.ts frontend/src/test/chartSpec.test.ts
git commit -m "feat(types): mirror ChartQuery filters/order/limit + date_range (Slice A)"
```

---

### Task 5: Frontend — CSV export utility

**Files:**
- Create: `frontend/src/lib/csv.ts`
- Test: `frontend/src/test/csv.test.ts` (create)

**Interfaces:**
- Produces: `toCsv(data: QueryResponse): string` and `downloadCsv(data: QueryResponse, filename: string): void`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/test/csv.test.ts`:

```typescript
import { describe, expect, it } from "vitest";
import { toCsv } from "@/lib/csv";
import type { QueryResponse } from "@/types/api";

describe("toCsv", () => {
  it("renders headers + rows", () => {
    const data: QueryResponse = {
      columns: ["region", "sales"],
      rows: [["west", 100], ["east", 200]],
      row_count: 2,
    };
    expect(toCsv(data)).toBe("region,sales\nwest,100\neast,200");
  });

  it("escapes commas, quotes, and newlines", () => {
    const data: QueryResponse = {
      columns: ["label", "note"],
      rows: [['a,b', 'he said "hi"'], ["line1\nline2", null]],
      row_count: 2,
    };
    expect(toCsv(data)).toBe('label,note\n"a,b","he said ""hi"""\n"line1\nline2",');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm test -- csv`
Expected: FAIL — module `@/lib/csv` not found.

- [ ] **Step 3: Implement `frontend/src/lib/csv.ts`**

```typescript
/**
 * CSV export for a QueryResponse. RFC-4180 escaping: a field is quoted when it
 * contains a comma, double-quote, or newline, and embedded quotes are doubled.
 */
import type { QueryResponse } from "@/types/api";

function escapeField(value: unknown): string {
  if (value === null || value === undefined) return "";
  const s = String(value);
  if (/[",\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

/** Serialise a QueryResponse to a CSV string (header row + data rows). */
export function toCsv(data: QueryResponse): string {
  const header = data.columns.map(escapeField).join(",");
  const rows = data.rows.map((row) => row.map(escapeField).join(","));
  return [header, ...rows].join("\n");
}

/** Trigger a browser download of the QueryResponse as a .csv file. */
export function downloadCsv(data: QueryResponse, filename: string): void {
  const blob = new Blob([toCsv(data)], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename.endsWith(".csv") ? filename : `${filename}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm test -- csv`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/csv.ts frontend/src/test/csv.test.ts
git commit -m "feat(chart): CSV export utility (Slice A)"
```

---

### Task 6: Frontend — unify `ChartQuery → SemanticQueryRequest` and forward filters/order/limit

**Files:**
- Modify: `frontend/src/lib/useChartData.ts`
- Test: `frontend/src/test/useChartData.test.ts` (create)

**Interfaces:**
- Produces: exported pure `buildSemanticRequest(spec: ChartSpec, viewFilters?: SemanticFilter[]): SemanticQueryRequest | null`. `useChartData` uses it; the builder (Task 9) reuses it for its live preview.
- Behaviour: forwards `spec.query.order` and `spec.query.limit` (fallback `200`); merges `spec.query.filters` with `viewFilters` (spec filters first, then view filters).

- [ ] **Step 1: Write the failing test**

Create `frontend/src/test/useChartData.test.ts`:

```typescript
import { describe, expect, it } from "vitest";
import { buildSemanticRequest } from "@/lib/useChartData";
import type { ChartSpec, SemanticFilter } from "@/types/api";

function specWith(query: Partial<ChartSpec["query"]>): ChartSpec {
  return {
    version: "1",
    type: "bar",
    query: { metric_refs: ["s.total"], dimensions: ["s.region"], ...query },
    encoding: { x: "s.region", series: [{ field: "s.total" }] },
  };
}

describe("buildSemanticRequest", () => {
  it("forwards order and limit from the spec", () => {
    const req = buildSemanticRequest(specWith({ order: { "s.total": "desc" }, limit: 25 }));
    expect(req?.order).toEqual({ "s.total": "desc" });
    expect(req?.limit).toBe(25);
  });

  it("defaults limit to 200 when the spec carries none", () => {
    expect(buildSemanticRequest(specWith({}))?.limit).toBe(200);
  });

  it("merges spec filters with view-time filters (spec first)", () => {
    const specFilter: SemanticFilter = { member: "s.region", operator: "equals", values: ["west"] };
    const viewFilter: SemanticFilter = { member: "s.tier", operator: "equals", values: ["gold"] };
    const req = buildSemanticRequest(specWith({ filters: [specFilter] }), [viewFilter]);
    expect(req?.filters).toEqual([specFilter, viewFilter]);
  });

  it("returns null for a non-semantic (dataset) spec", () => {
    const spec = specWith({});
    spec.query.metric_refs = [];
    expect(buildSemanticRequest(spec)).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm test -- useChartData`
Expected: FAIL — `buildSemanticRequest` not exported.

- [ ] **Step 3: Implement in `frontend/src/lib/useChartData.ts`**

Replace the body of the file's request construction. Add the exported helper and call it from the hook:

```typescript
const DEFAULT_LIMIT = 200;

/**
 * Build the SemanticQueryRequest a ChartSpec describes. Forwards spec-level
 * order/limit/filters and merges any view-time filters (spec filters first).
 * Returns null for a non-semantic (dataset) spec.
 */
export function buildSemanticRequest(
  spec: ChartSpec | null,
  viewFilters?: SemanticFilter[]
): SemanticQueryRequest | null {
  const metricRefs = spec?.query.metric_refs ?? [];
  if (!spec || metricRefs.length === 0) return null;

  const timeDimensions = spec.query.time_dimensions ?? [];
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

Then simplify `useChartData` to use it:

```typescript
export function useChartData(spec: ChartSpec | null, filters?: SemanticFilter[]) {
  const isSemantic = (spec?.query.metric_refs ?? []).length > 0;

  const semanticRequest = buildSemanticRequest(spec, filters);

  const datasetId =
    !isSemantic && spec?.query.dataset_id && spec.query.query ? spec.query.dataset_id : null;
  const datasetRequest = spec?.query.query ?? EMPTY_QUERY;

  const semantic = useSemanticQuery(semanticRequest);
  const dataset = useDatasetQuery(datasetId, datasetRequest);

  return isSemantic ? semantic : dataset;
}
```

Keep the `EMPTY_QUERY` constant and update the imports (`ChartSpec` is already imported).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm test -- useChartData`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/useChartData.ts frontend/src/test/useChartData.test.ts
git commit -m "feat(chart): forward spec filters/order/limit through useChartData (Slice A)"
```

---

### Task 7: Frontend — `ChartRenderer` exposes a `toPng()` handle

**Files:**
- Modify: `frontend/src/components/chart/ChartRenderer.tsx`
- Test: `frontend/src/test/chartRenderer.test.ts` (add a guard test for the handle type — the existing file already tests `buildEChartsOption`)

**Interfaces:**
- Produces: exported `interface ChartRendererHandle { toPng: () => string | null }`. `ChartRenderer` becomes `forwardRef<ChartRendererHandle, ChartRendererProps>`; `toPng()` returns the ECharts `getDataURL()` PNG, or `null` for table/number renders or before init.

- [ ] **Step 1: Implement in `frontend/src/components/chart/ChartRenderer.tsx`**

Add `forwardRef` and `useImperativeHandle` to the React import:

```typescript
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
```

Export the handle type near the props interface:

```typescript
export interface ChartRendererHandle {
  /** PNG data URL of the current chart, or null for non-ECharts renders. */
  toPng: () => string | null;
}
```

Convert the component signature to `forwardRef` and wire the handle. Change:

```typescript
export function ChartRenderer({
  spec,
  data,
  title,
  className = "",
  onSelectCategory,
}: ChartRendererProps) {
```

to:

```typescript
export const ChartRenderer = forwardRef<ChartRendererHandle, ChartRendererProps>(function ChartRenderer(
  { spec, data, title, className = "", onSelectCategory },
  ref
) {
```

Add, just after the `useTheme()` line:

```typescript
  useImperativeHandle(
    ref,
    () => ({
      toPng: () =>
        chartRef.current
          ? chartRef.current.getDataURL({ type: "png", pixelRatio: 2, backgroundColor: "transparent" })
          : null,
    }),
    []
  );
```

Close the component with `});` instead of `}` at the end of the function.

- [ ] **Step 2: Add the handle-type guard test**

Append to `frontend/src/test/chartRenderer.test.ts`:

```typescript
import type { ChartRendererHandle } from "@/components/chart/ChartRenderer";

test("ChartRendererHandle exposes toPng", () => {
  const handle: ChartRendererHandle = { toPng: () => null };
  expect(handle.toPng()).toBeNull();
});
```

- [ ] **Step 3: Run test + typecheck**

Run: `cd frontend && pnpm exec tsc --noEmit && pnpm test -- chartRenderer`
Expected: typecheck clean (all existing `<ChartRenderer .../>` usages still compile — `forwardRef` keeps the same props); tests PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/chart/ChartRenderer.tsx frontend/src/test/chartRenderer.test.ts
git commit -m "feat(chart): expose toPng() handle on ChartRenderer (Slice A)"
```

---

### Task 8: Frontend — `ChartActionsMenu` (view as table / view query / download CSV / PNG)

**Files:**
- Create: `frontend/src/components/chart/ChartActionsMenu.tsx`
- Test: `frontend/src/test/chartActionsMenu.test.tsx` (create)

**Interfaces:**
- Consumes: `downloadCsv` (Task 5), `ChartRendererHandle` (Task 7), `TableRenderer`, `Dialog` family from `@/components/ui/dialog`.
- Produces: `ChartActionsMenu` component. Props: `{ spec: ChartSpec; data: QueryResponse; chartHandle?: React.RefObject<ChartRendererHandle | null>; title?: string }`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/test/chartActionsMenu.test.tsx`:

```typescript
import { describe, expect, it } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ChartActionsMenu } from "@/components/chart/ChartActionsMenu";
import type { ChartSpec, QueryResponse } from "@/types/api";

const data: QueryResponse = { columns: ["region", "sales"], rows: [["west", 100]], row_count: 1 };

function specOfType(type: ChartSpec["type"]): ChartSpec {
  return {
    version: "1",
    type,
    query: { metric_refs: ["s.sales"], dimensions: ["s.region"] },
    encoding: { x: "s.region", series: [{ field: "s.sales" }] },
  };
}

describe("ChartActionsMenu", () => {
  it("offers View as table and View query", () => {
    render(<ChartActionsMenu spec={specOfType("bar")} data={data} title="Sales" />);
    fireEvent.click(screen.getByRole("button", { name: /chart actions/i }));
    expect(screen.getByText(/view as table/i)).toBeInTheDocument();
    expect(screen.getByText(/view query/i)).toBeInTheDocument();
    expect(screen.getByText(/download csv/i)).toBeInTheDocument();
  });

  it("hides Download PNG for table charts", () => {
    render(<ChartActionsMenu spec={specOfType("table")} data={data} title="T" />);
    fireEvent.click(screen.getByRole("button", { name: /chart actions/i }));
    expect(screen.queryByText(/download png/i)).not.toBeInTheDocument();
  });

  it("shows the semantic query (not SQL) in View query", () => {
    render(<ChartActionsMenu spec={specOfType("bar")} data={data} title="Sales" />);
    fireEvent.click(screen.getByRole("button", { name: /chart actions/i }));
    fireEvent.click(screen.getByText(/view query/i));
    expect(screen.getByText(/metric_refs/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm test -- chartActionsMenu`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `frontend/src/components/chart/ChartActionsMenu.tsx`**

```tsx
/**
 * ChartActionsMenu — Superset-style "⋯" actions on a chart (Slice A).
 *
 * View as table (re-renders the same QueryResponse as a table), View query (the
 * grounded *semantic* query — never SQL), Download CSV, and Download PNG (via the
 * renderer's toPng handle; hidden for non-ECharts table/number charts).
 */
import { useState } from "react";
import { MoreHorizontal } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { TableRenderer } from "@/components/chart/TableRenderer";
import type { ChartRendererHandle } from "@/components/chart/ChartRenderer";
import { downloadCsv } from "@/lib/csv";
import type { ChartSpec, QueryResponse } from "@/types/api";

interface ChartActionsMenuProps {
  spec: ChartSpec;
  data: QueryResponse;
  /** Ref to the rendered chart for PNG export; omit for table/number tiles. */
  chartHandle?: React.RefObject<ChartRendererHandle | null>;
  title?: string;
}

export function ChartActionsMenu({ spec, data, chartHandle, title = "chart" }: ChartActionsMenuProps) {
  const [open, setOpen] = useState(false);
  const [showTable, setShowTable] = useState(false);
  const [showQuery, setShowQuery] = useState(false);

  const isEcharts = spec.type !== "table" && spec.type !== "number";

  function handlePng() {
    const url = chartHandle?.current?.toPng();
    if (!url) return;
    const a = document.createElement("a");
    a.href = url;
    a.download = `${title}.png`;
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  return (
    <>
      <details
        open={open}
        onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}
        className="relative"
      >
        <summary className="inline-flex h-8 w-8 cursor-pointer list-none items-center justify-center rounded-md border text-muted-foreground hover:bg-accent hover:text-foreground [&::-webkit-details-marker]:hidden">
          <MoreHorizontal className="h-4 w-4" aria-hidden />
          <span className="sr-only">Chart actions</span>
        </summary>
        <div className="absolute right-0 z-30 mt-1 w-44 rounded-md border bg-popover p-1 shadow-md">
          <MenuItem onClick={() => { setShowTable(true); setOpen(false); }}>View as table</MenuItem>
          <MenuItem onClick={() => { setShowQuery(true); setOpen(false); }}>View query</MenuItem>
          <MenuItem onClick={() => { downloadCsv(data, title); setOpen(false); }}>Download CSV</MenuItem>
          {isEcharts && (
            <MenuItem onClick={() => { handlePng(); setOpen(false); }}>Download PNG</MenuItem>
          )}
        </div>
      </details>

      <Dialog open={showTable} onOpenChange={setShowTable} title="View as table">
        <DialogHeader>
          <DialogTitle>{title} — table</DialogTitle>
          <DialogDescription>The same query result, shown as a table.</DialogDescription>
        </DialogHeader>
        <div className="max-h-[60vh] overflow-auto">
          <TableRenderer spec={spec} data={data} />
        </div>
      </Dialog>

      <Dialog open={showQuery} onOpenChange={setShowQuery} title="View query">
        <DialogHeader>
          <DialogTitle>Semantic query</DialogTitle>
          <DialogDescription>
            The grounded semantic query this chart runs — governed members only, no SQL.
          </DialogDescription>
        </DialogHeader>
        <pre className="max-h-[60vh] overflow-auto rounded-md bg-muted p-3 text-xs">
          {JSON.stringify(spec.query, null, 2)}
        </pre>
      </Dialog>
    </>
  );
}

function MenuItem({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="block w-full rounded px-2 py-1.5 text-left text-sm hover:bg-accent"
    >
      {children}
    </button>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm test -- chartActionsMenu`
Expected: PASS. If `TableRenderer` requires props beyond `spec`/`data`, check its signature in `frontend/src/components/chart/TableRenderer.tsx` and pass what it needs (it currently takes `{ spec, data, className? }`).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/chart/ChartActionsMenu.tsx frontend/src/test/chartActionsMenu.test.tsx
git commit -m "feat(chart): ChartActionsMenu (view table/query, download CSV/PNG) (Slice A)"
```

---

### Task 9: Frontend — builder Query controls (time range, row limit, server sort)

**Files:**
- Modify: `frontend/src/pages/Builder.tsx` (`useSemanticBuilder` state + spec + preview request + `loadSpec`)
- Create: `frontend/src/components/chart/QueryControls.tsx`
- Test: `frontend/src/test/builderQuery.test.ts` (create)

**Interfaces:**
- Consumes: `buildSemanticRequest` (Task 6), `RelativeDateRange` (Task 4).
- Produces: exported pure `buildChartQuery(args: BuilderQueryState): ChartQuery` from `Builder.tsx`, used both for `spec.query` and (via `buildSemanticRequest`) the live preview. `SemanticBuilder` gains `rowLimit`/`setRowLimit`, `dateRange`/`setDateRange`, `orderBy`/`setOrderBy`.

- [ ] **Step 1: Write the failing test for the pure query builder**

Create `frontend/src/test/builderQuery.test.ts`:

```typescript
import { describe, expect, it } from "vitest";
import { buildChartQuery } from "@/pages/Builder";

describe("buildChartQuery", () => {
  it("emits time_dimensions with date_range, order, and limit", () => {
    const q = buildChartQuery({
      measures: ["s.total"],
      plainDims: [],
      timeDimension: { dimension: "s.created", granularity: "month" },
      dateRange: "last_30_days",
      filters: [],
      orderBy: { member: "s.total", dir: "desc" },
      rowLimit: 25,
    });
    expect(q.time_dimensions).toEqual([
      { dimension: "s.created", granularity: "month", date_range: "last_30_days" },
    ]);
    expect(q.order).toEqual({ "s.total": "desc" });
    expect(q.limit).toBe(25);
    expect(q.metric_refs).toEqual(["s.total"]);
  });

  it("omits order when no sort is chosen and omits date_range when unset", () => {
    const q = buildChartQuery({
      measures: ["s.total"],
      plainDims: ["s.region"],
      timeDimension: null,
      dateRange: null,
      filters: [],
      orderBy: null,
      rowLimit: 50,
    });
    expect(q.order).toEqual({});
    expect(q.time_dimensions).toEqual([]);
    expect(q.dimensions).toEqual(["s.region"]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm test -- builderQuery`
Expected: FAIL — `buildChartQuery` not exported.

- [ ] **Step 3: Implement `buildChartQuery` + state in `frontend/src/pages/Builder.tsx`**

Add the exported types + pure function near the top (after the imports):

```typescript
export interface BuilderQueryState {
  measures: string[];
  plainDims: string[];
  timeDimension: { dimension: string; granularity: SemanticGranularity } | null;
  dateRange: RelativeDateRange | string[] | null;
  filters: SemanticFilter[];
  orderBy: { member: string; dir: "asc" | "desc" } | null;
  rowLimit: number;
}

/** Build the spec's ChartQuery from the builder's shelf + query-control state. */
export function buildChartQuery(s: BuilderQueryState): ChartQuery {
  const timeDimensions = s.timeDimension
    ? [
        {
          dimension: s.timeDimension.dimension,
          granularity: s.timeDimension.granularity,
          ...(s.dateRange ? { date_range: s.dateRange } : {}),
        },
      ]
    : [];
  return {
    metric_refs: s.measures,
    dimensions: s.plainDims,
    time_dimensions: timeDimensions,
    filters: s.filters,
    order: s.orderBy ? { [s.orderBy.member]: s.orderBy.dir } : {},
    limit: s.rowLimit,
  };
}
```

Add the imports `ChartQuery`, `RelativeDateRange`, `SemanticFilter` to the existing `@/types/api` import.

In `useSemanticBuilder`, add state (after the existing `format` state):

```typescript
  const [rowLimit, setRowLimit] = useState(DEFAULT_LIMIT);
  const [dateRange, setDateRange] = useState<RelativeDateRange | string[] | null>(null);
  const [orderBy, setOrderBy] = useState<{ member: string; dir: "asc" | "desc" } | null>(null);
  const [filters, setFilters] = useState<SemanticFilter[]>([]);
```

Replace the `request`/`spec` construction so both derive from `buildChartQuery`:

```typescript
  const query = buildChartQuery({
    measures,
    plainDims,
    timeDimension: isTimeX && xDim ? { dimension: xDim, granularity } : null,
    dateRange,
    filters,
    orderBy,
    rowLimit,
  });

  const spec: ChartSpec = {
    version: "1",
    type: chartType,
    query,
    encoding: {
      x: xField,
      series,
      ...(hasBreakdown ? { breakdown } : {}),
    },
    options: toChartOptions(title, format),
  };

  const request = ready ? buildSemanticRequest(spec) : null;
  const result = useSemanticQuery(request);
```

(Remove the old hand-built `request`/`timeDimensions`/`SemanticQueryRequest` block this replaces; keep `plainDims`, `xField`, `series`, `hasBreakdown`, `title`, `ready` as they are. Import `buildSemanticRequest` from `@/lib/useChartData`.)

Extend `loadSpec` to restore the new controls (add at the end of the function):

```typescript
    setRowLimit(loaded.query.limit ?? DEFAULT_LIMIT);
    setDateRange(td[0]?.date_range ?? null);
    setFilters(loaded.query.filters ?? []);
    const orderEntry = Object.entries(loaded.query.order ?? {})[0];
    setOrderBy(orderEntry ? { member: orderEntry[0], dir: orderEntry[1] as "asc" | "desc" } : null);
```

Add the new fields to the hook's return object:

```typescript
    rowLimit,
    setRowLimit,
    dateRange,
    setDateRange,
    orderBy,
    setOrderBy,
    filters,
    setFilters,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm test -- builderQuery`
Expected: PASS.

- [ ] **Step 5: Create the `QueryControls` UI**

Create `frontend/src/components/chart/QueryControls.tsx`:

```tsx
/**
 * QueryControls — Superset-Explore query shaping for the builder (Slice A):
 * time range (when the x-axis is a time dimension), server "Sort by", and row limit.
 * Filters live on their own shelf in SemanticQueryBuilder.
 */
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { humanize } from "@/lib/format";
import type { RelativeDateRange } from "@/types/api";
import type { SemanticBuilder } from "@/pages/Builder";

const RELATIVE_RANGES: RelativeDateRange[] = [
  "last_7_days",
  "last_30_days",
  "last_90_days",
  "this_month",
  "last_month",
  "this_quarter",
  "last_quarter",
  "this_year",
  "last_year",
];

export function QueryControls({ s }: { s: SemanticBuilder }) {
  // Sortable members = the queried measures + the category dimension.
  const sortMembers = [...s.measures, ...(s.xDim ? [s.xDim] : [])];
  const isCustom = Array.isArray(s.dateRange);

  return (
    <details className="rounded-lg border bg-background/40 p-3" open>
      <summary className="cursor-pointer text-sm font-medium">Query</summary>
      <div className="mt-3 space-y-3">
        {s.isTimeX && (
          <div className="space-y-1.5">
            <Label htmlFor="q-range">Time range</Label>
            <Select
              id="q-range"
              value={isCustom ? "custom" : (s.dateRange ?? "none")}
              onChange={(e) => {
                const v = e.target.value;
                if (v === "none") s.setDateRange(null);
                else if (v === "custom") s.setDateRange(["", ""]);
                else s.setDateRange(v as RelativeDateRange);
              }}
            >
              <option value="none">No filter</option>
              {RELATIVE_RANGES.map((r) => (
                <option key={r} value={r}>{humanize(r)}</option>
              ))}
              <option value="custom">Custom range…</option>
            </Select>
            {isCustom && (
              <div className="grid grid-cols-2 gap-2">
                <Input
                  type="date"
                  aria-label="From"
                  value={(s.dateRange as string[])[0]}
                  onChange={(e) => s.setDateRange([e.target.value, (s.dateRange as string[])[1]])}
                />
                <Input
                  type="date"
                  aria-label="To"
                  value={(s.dateRange as string[])[1]}
                  onChange={(e) => s.setDateRange([(s.dateRange as string[])[0], e.target.value])}
                />
              </div>
            )}
          </div>
        )}

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="q-sort">Sort by (query)</Label>
            <Select
              id="q-sort"
              value={s.orderBy?.member ?? ""}
              onChange={(e) =>
                s.setOrderBy(e.target.value ? { member: e.target.value, dir: s.orderBy?.dir ?? "desc" } : null)
              }
            >
              <option value="">None</option>
              {sortMembers.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="q-dir">Direction</Label>
            <Select
              id="q-dir"
              value={s.orderBy?.dir ?? "desc"}
              disabled={!s.orderBy}
              onChange={(e) =>
                s.orderBy && s.setOrderBy({ member: s.orderBy.member, dir: e.target.value as "asc" | "desc" })
              }
            >
              <option value="desc">Descending</option>
              <option value="asc">Ascending</option>
            </Select>
          </div>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="q-limit">Row limit</Label>
          <Input
            id="q-limit"
            type="number"
            min={1}
            value={s.rowLimit}
            onChange={(e) => s.setRowLimit(Math.max(1, Number(e.target.value) || 1))}
          />
        </div>
      </div>
    </details>
  );
}
```

Render it in `Builder.tsx` inside the Configure card, between `<SemanticQueryBuilder s={semantic} />` and `<FormatControls .../>`:

```tsx
            <SemanticQueryBuilder s={semantic} />
            <QueryControls s={semantic} />
            <FormatControls format={semantic.format} setFormat={semantic.setFormat} />
```

Add `import { QueryControls } from "@/components/chart/QueryControls";` to `Builder.tsx`.

- [ ] **Step 6: Run typecheck + tests**

Run: `cd frontend && pnpm exec tsc --noEmit && pnpm test -- builderQuery`
Expected: typecheck clean; tests PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/Builder.tsx frontend/src/components/chart/QueryControls.tsx frontend/src/test/builderQuery.test.ts
git commit -m "feat(builder): time-range, server sort, and row-limit controls (Slice A)"
```

---

### Task 10: Frontend — Filters shelf in the builder

**Files:**
- Modify: `frontend/src/components/chart/SemanticQueryBuilder.tsx` (add a Filters shelf + editor)
- Test: `frontend/src/test/semanticQueryBuilder.test.tsx` (create)

**Interfaces:**
- Consumes: `s.filters`, `s.setFilters` (Task 9), the governed `SemanticFilterOperator` set.
- Produces: a "Filters" droppable shelf; dropping a dimension/measure appends a `SemanticFilter` (default operator `equals`, empty values); each placed filter is an inline editable row (operator select + comma-separated values input + remove).

- [ ] **Step 1: Write the failing test**

Create `frontend/src/test/semanticQueryBuilder.test.tsx`:

```typescript
import { describe, expect, it } from "vitest";
import { filtersAfterDrop, parseFilterValues } from "@/components/chart/SemanticQueryBuilder";
import type { SemanticFilter } from "@/types/api";

describe("filter helpers", () => {
  it("appends a default-equals filter for a dropped member", () => {
    const next = filtersAfterDrop([], "s.region");
    expect(next).toEqual([{ member: "s.region", operator: "equals", values: [] }]);
  });

  it("does not duplicate a member already filtered", () => {
    const existing: SemanticFilter[] = [{ member: "s.region", operator: "equals", values: ["west"] }];
    expect(filtersAfterDrop(existing, "s.region")).toBe(existing);
  });

  it("parses comma-separated values, trimming blanks", () => {
    expect(parseFilterValues("west, east ,")).toEqual(["west", "east"]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm test -- semanticQueryBuilder`
Expected: FAIL — helpers not exported.

- [ ] **Step 3: Implement the helpers + shelf in `frontend/src/components/chart/SemanticQueryBuilder.tsx`**

Add exported pure helpers near the top (after `SHELF_ACCEPTS`):

```typescript
/** Append a default `equals` filter for a member, unless it is already filtered. */
export function filtersAfterDrop(filters: SemanticFilter[], member: string): SemanticFilter[] {
  if (filters.some((f) => f.member === member)) return filters;
  return [...filters, { member, operator: "equals", values: [] }];
}

/** Split a comma-separated values string into trimmed, non-empty values. */
export function parseFilterValues(raw: string): string[] {
  return raw.split(",").map((v) => v.trim()).filter(Boolean);
}

const FILTER_OPERATORS: SemanticFilterOperator[] = [
  "equals",
  "notEquals",
  "contains",
  "notContains",
  "gt",
  "gte",
  "lt",
  "lte",
  "set",
  "notSet",
];

const VALUELESS_OPERATORS: SemanticFilterOperator[] = ["set", "notSet"];
```

Import the filter types: add `SemanticFilter`, `SemanticFilterOperator` to the `@/types/api` import.

Add `filters: "any"` handling: extend `SHELF_ACCEPTS` is keyed by `FieldKind`; the Filters shelf accepts both kinds, so special-case it in `handleDragEnd`. Update `handleDragEnd`:

```typescript
  function handleDragEnd(e: DragEndEvent) {
    setDragLabel(null);
    const data = e.active.data.current as DragData | undefined;
    const shelf = e.over?.id as string | undefined;
    if (!data || !shelf) return;
    if (shelf === "filters") {
      s.setFilters(filtersAfterDrop(s.filters, data.field));
      return;
    }
    if (SHELF_ACCEPTS[shelf] !== data.kind) return;
    if (shelf === "x") s.setXDim(data.field);
    else if (shelf === "breakdown") s.addBreakdown(data.field);
    else if (shelf === "metrics") s.addMeasure(data.field);
  }
```

Add a Filters shelf + editor after the Metrics shelf (after the closing `</Shelf>` of metrics, before the chart-type select):

```tsx
        <Shelf
          id="filters"
          label="Filters"
          hint="Drop a field to filter on it"
          empty={s.filters.length === 0}
        >
          {s.filters.map((f) => (
            <FilterRow
              key={f.member}
              filter={f}
              onChange={(next) =>
                s.setFilters(s.filters.map((x) => (x.member === f.member ? next : x)))
              }
              onRemove={() => s.setFilters(s.filters.filter((x) => x.member !== f.member))}
            />
          ))}
        </Shelf>
```

Add the `FilterRow` component at the end of the file:

```tsx
function FilterRow({
  filter,
  onChange,
  onRemove,
}: {
  filter: SemanticFilter;
  onChange: (next: SemanticFilter) => void;
  onRemove: () => void;
}) {
  const valueless = VALUELESS_OPERATORS.includes(filter.operator);
  return (
    <div className="flex w-full flex-wrap items-center gap-1.5 rounded-md border bg-background/60 p-1.5">
      <span className="truncate text-xs font-medium" title={filter.member}>
        {filter.member}
      </span>
      <Select
        aria-label={`Operator for ${filter.member}`}
        value={filter.operator}
        onChange={(e) =>
          onChange({ ...filter, operator: e.target.value as SemanticFilterOperator, values: [] })
        }
        className="h-7 w-28 text-xs"
      >
        {FILTER_OPERATORS.map((op) => (
          <option key={op} value={op}>{op}</option>
        ))}
      </Select>
      {!valueless && (
        <input
          aria-label={`Values for ${filter.member}`}
          defaultValue={filter.values.join(", ")}
          onBlur={(e) => onChange({ ...filter, values: parseFilterValues(e.target.value) })}
          placeholder="value(s), comma-separated"
          className="h-7 flex-1 rounded border bg-transparent px-2 text-xs"
        />
      )}
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Remove filter ${filter.member}`}
        className="rounded p-0.5 text-muted-foreground hover:text-destructive"
      >
        <X className="h-3 w-3" />
      </button>
    </div>
  );
}
```

(`X` is already imported from lucide-react in this file.)

- [ ] **Step 4: Run test + typecheck**

Run: `cd frontend && pnpm exec tsc --noEmit && pnpm test -- semanticQueryBuilder`
Expected: typecheck clean; tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/chart/SemanticQueryBuilder.tsx frontend/src/test/semanticQueryBuilder.test.tsx
git commit -m "feat(builder): Filters shelf with per-field operator + values (Slice A)"
```

---

### Task 11: Frontend — wire ChartActionsMenu into the builder preview + dashboard tiles; full verification

**Files:**
- Modify: `frontend/src/pages/Builder.tsx` (`SemanticPreview` — attach a chart ref + actions menu)
- Modify: `frontend/src/components/dashboard/DashboardCardTile.tsx` (`ChartTileBody` — attach a ref + actions menu)
- Modify: `docs/CHART_SPEC.md` if not already covering the actions (cross-check)

**Interfaces:**
- Consumes: `ChartActionsMenu` (Task 8), `ChartRendererHandle` (Task 7).

- [ ] **Step 1: Add the actions menu to the builder preview**

In `frontend/src/pages/Builder.tsx`, `SemanticPreview`: create a ref and pass it to the renderer, and add the menu beside the Save/Add buttons. Add the imports:

```typescript
import { useRef } from "react";
import { ChartRenderer, type ChartRendererHandle } from "@/components/chart/ChartRenderer";
import { ChartActionsMenu } from "@/components/chart/ChartActionsMenu";
```

(Replace the existing `ChartRenderer` import line.) Inside `SemanticPreview`, before the return:

```typescript
  const chartHandle = useRef<ChartRendererHandle>(null);
```

In the `CardHeader` actions cluster (where `SaveChartButton`/`AddToDashboard` are, shown only when `s.ready && hasData`), add as the first child:

```tsx
            <ChartActionsMenu spec={s.spec} data={data} chartHandle={chartHandle} title={s.spec.options?.title ?? "Chart"} />
```

And pass the ref to the renderer in the `hasData` branch:

```tsx
          <ChartRenderer
            ref={chartHandle}
            spec={s.spec}
            data={data}
            title={s.spec.options?.title ?? undefined}
            className="h-80"
          />
```

- [ ] **Step 2: Add the actions menu to dashboard chart tiles**

In `frontend/src/components/dashboard/DashboardCardTile.tsx`, `ChartTileBody`: add a ref and render the menu in the tile header area. Update imports:

```typescript
import { useRef } from "react";
import { ChartRenderer, type ChartRendererHandle } from "@/components/chart/ChartRenderer";
import { ChartActionsMenu } from "@/components/chart/ChartActionsMenu";
```

In `ChartTileBody`, before the return, add:

```typescript
  const chartHandle = useRef<ChartRendererHandle>(null);
```

Pass the ref to the renderer:

```tsx
        <ChartRenderer
          ref={chartHandle}
          spec={spec}
          data={data}
          title={title}
          className="h-64"
          onSelectCategory={editing ? undefined : onSelectCategory}
        />
```

And render the menu (only when data is present and not editing) just above the `ChartRenderer`'s wrapping fragment, e.g. inside the `data && data.row_count > 0` branch, wrap with a relative container and place the menu top-right:

```tsx
      ) : data && data.row_count > 0 ? (
        <div className="relative h-full">
          {!editing && (
            <div className="absolute right-0 top-0 z-10">
              <ChartActionsMenu spec={spec} data={data} chartHandle={chartHandle} title={title} />
            </div>
          )}
          <ChartRenderer
            ref={chartHandle}
            spec={spec}
            data={data}
            title={title}
            className="h-64"
            onSelectCategory={editing ? undefined : onSelectCategory}
          />
        </div>
      ) : isError ? (
```

- [ ] **Step 3: Typecheck + run the whole frontend suite**

Run: `cd frontend && pnpm exec tsc --noEmit && pnpm test && pnpm lint`
Expected: all green. Fix any prop/type mismatches surfaced (e.g. ensure existing dashboard tests `dashboardCardTile.test.tsx` still pass — the menu only renders when `!editing` and data is present).

- [ ] **Step 4: Run the whole backend suite**

Run: `cd backend && uv run pytest && uv run ruff check . && uv run mypy app`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Builder.tsx frontend/src/components/dashboard/DashboardCardTile.tsx
git commit -m "feat(chart): wire ChartActionsMenu into builder preview + dashboard tiles (Slice A)"
```

---

## Self-Review (completed during planning)

**Spec coverage** — every slice-A spec item maps to a task:
- Time-range filtering → Tasks 1, 2 (backend) + Task 9 (UI).
- Per-chart filters → Task 3 (persist) + Task 6 (forward/merge) + Task 10 (UI).
- Row limit → Task 3 (persist) + Task 6 (forward) + Task 9 (UI).
- Server sort → Task 3 (persist) + Task 6 (forward) + Task 9 (UI).
- Chart actions (view as table / view query / download CSV / PNG) → Tasks 5, 7, 8 + wiring Task 11.
- `useChartData` merge → Task 6. Type mirror → Task 4. Docs → Task 3 (CHART_SPEC) ; fixture → Task 3.
- Tenancy/golden rules: filter/order allow-list re-validation already covered by existing `_check_grounded` and `test_query_rejects_ungoverned_filter_member`; "View query" shows `spec.query` (semantic), not SQL (Task 8 test asserts `metric_refs` present).

**Type consistency** — `buildSemanticRequest` (Task 6) is the single ChartQuery→request mapper used by both `useChartData` and the builder preview (Task 9); `ChartRendererHandle.toPng` (Task 7) is consumed unchanged by `ChartActionsMenu` (Task 8) and the wiring (Task 11); `buildChartQuery`'s `BuilderQueryState` (Task 9) and the filter helpers (Task 10) share the `SemanticFilter` shape from `types/api.ts` (Task 4).

**Placeholder scan** — no TBD/TODO; every code step contains complete code.
