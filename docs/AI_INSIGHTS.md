# AI Insights & Source-Based Suggestions (Phase 4, Task 4.5)

Two AI sub-features that follow the [nl-to-sql-grounding skill](../.claude/skills/nl-to-sql-grounding/SKILL.md) four-stage pattern (Ground -> Generate -> Validate -> Execute/Return).

---

## Sub-feature (a): Dashboard Insight Summaries

**Endpoint:** `POST /api/v1/ai/insights`

### What it does

Generates a 2-4 sentence natural-language summary of an already-computed result set (the dashboard's own data). The endpoint does NOT re-query any data — the caller supplies the result set as part of the request body.

### Request schema

```json
{
  "columns": ["region", "revenue", "order_count"],
  "rows": [
    ["EMEA", 142500, 1200],
    ["APAC", 98300, 800],
    ["AMER", 201000, 1800]
  ],
  "context_hint": "Q3 Regional Sales"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `columns` | `list[str]` | Column names (required, min 1) |
| `rows` | `list[list[Any]]` | Data rows aligned with columns |
| `context_hint` | `str \| null` | Optional dashboard title or question (max 500 chars) |

### Response schema

```json
{
  "summary": "AMER led all regions with $201,000 in revenue from 1,800 orders..."
}
```

On failure (422):
```json
{
  "detail": "The generated summary contains numbers that cannot be verified against the result set data. Please try again."
}
```

### Four-stage pipeline

1. **Ground**: The result set is the grounding context — serialised to a compact CSV-like text (capped at 100 rows / 20 columns to keep tokens bounded and limit PII exposure).
2. **Generate**: LLM called via `LLMGateway.complete()` using the `insights/v1` system template, which injects `{result_set}` and instructs "do NOT invent numbers".
3. **Validate** (the no-invented-numbers guardrail — see below).
4. **Return**: The validated summary text.

---

### No-invented-numbers guardrail

**Module:** `app/ai/insights/guardrail.py` — `verify_no_invented_numbers(summary, *, columns, rows)`

This is the critical safety invariant: summaries must only reference numbers present in the result set. It is implemented as a **pure function** (no I/O) so it can be unit-tested exhaustively without mocking.

#### Algorithm

**Step 1 — Extract numeric tokens from the summary**

Every numeric value in the summary is extracted via regex, stripping common display formatting:
- Thousands separators: `1,234` -> `1234`
- Currency symbols: `$3.5`, `£1,200`, `€500`
- Percentage markers: `12.5%` -> `12.5`
- Leading minus: `-45`

**Step 2 — Build the reference set from the result set**

Every cell value in `rows` that can be converted to `float` is collected as a reference value. Booleans are excluded (True=1 / False=0 are too generic). Non-numeric strings are silently skipped.

**Step 3 — Traceability check for each extracted number**

For each number found in the summary, check if it is traceable to at least one reference value using these rules (applied in order, first match wins):

| Rule | Description | Example |
|------|-------------|---------|
| Exact match | `ref == value` | Data: `1234`, summary: `1234` |
| Rounded match | `round(ref, k) == round(value, k)` for k in 0..4 | Data: `142500.876`, summary: `142501` |
| K/M scaled match | `ref / 1000 ≈ value` or `ref / 1e6 ≈ value` (within 0.5%) | Data: `1500`, summary: `1.5` (representing "1.5K") |

The scale factor tolerance is **not** applied for factors below 1000x. This prevents spurious matches like 9999 being "traced" to 100 via a 100x factor.

**Step 4 — Fail closed on any untraceable number**

If ANY extracted number cannot be traced, `InsightGuardrailError` is raised. The service layer makes one bounded retry before propagating the error as a 422 response.

#### Test coverage

Direct unit tests in `tests/test_insights.py` (Part A) cover:
- Numbers present in data: pass
- Rounded numbers (e.g. `142501` from `142500.876`): pass
- Currency/thousands-formatted numbers: pass
- Invented numbers not in data: raises `InsightGuardrailError`
- No numbers in summary: pass (trivially)
- Multiple numbers, one invented: raises

---

## Sub-feature (b): Source-Based Chart Suggestions

**Endpoint:** `POST /api/v1/ai/datasets/{dataset_id}/suggestions`

### What it does

Profiles a tenant-owned dataset and generates 3-5 validated `ChartSpec` suggestions grounded on the dataset's actual columns.

### Response schema

```json
{
  "suggestions": [
    {
      "title": "Revenue by Region",
      "rationale": "Shows how revenue is distributed across geographic regions.",
      "spec": {
        "version": "1",
        "type": "bar",
        "query": {
          "dataset_id": "uuid-of-dataset",
          "query": {
            "dimensions": ["region"],
            "metrics": [{"function": "sum", "column": "revenue", "alias": "total_revenue"}],
            "filters": [],
            "limit": 1000
          }
        },
        "encoding": {
          "x": "region",
          "series": [{"field": "total_revenue", "name": "Total Revenue"}]
        },
        "options": {"title": "Revenue by Region", "stacked": false, "show_legend": true}
      }
    }
  ],
  "note": null
}
```

When no valid suggestions are generated, `suggestions` is `[]` and `note` explains why (never a 500).

On 404: dataset not found or not owned by the authenticated tenant.

### Four-stage pipeline

1. **Ground**: 
   - Dataset ownership verified via `DatasetService.get_for_tenant(ctx, dataset_id)` — returns 404 if the dataset is not owned by the authenticated tenant. **The tenant ID is never taken from the request body.**
   - Dataset profiled via `DatasetProfiler` (see "PII-aware profiling" below).

2. **Generate**: LLM called via `LLMGateway.complete()` using the `suggestions/v1` prompt template, which injects `{dataset_profile}` and `{dataset_id}`.

3. **Validate** (per-suggestion):
   - **Schema strict**: each `spec` validated against `ChartSpec` with `extra="forbid"` (mirrors the `nl_chart/validator.py` approach).
   - **Inline-dataset path gate**: suggestions MUST use `query.dataset_id + query.query` (NOT `metric_refs`, which is the semantic-layer path).
   - **Dataset-ID check**: `spec.query.dataset_id` must exactly match the profiled dataset's UUID.
   - **Column allow-list** (the key safety gate): every column name referenced in the suggestion (dimensions, metric columns, `encoding.x`, `encoding.series[].field` via alias) must exist in the profiled column set. The LLM cannot invent columns.
   Invalid suggestions are silently dropped.

4. **Return**: List of validated `{title, rationale, spec}` items (may be empty).

---

### PII-aware dataset profiling

**Module:** `app/ai/insights/profiler.py`

The profiler runs read-only queries against the tenant's ClickHouse database (all queries go through `ClickHouseDatasetService.run_read_only_query`, which is bound to `ctx.clickhouse_db`).

Queries executed per dataset:
1. `DESCRIBE <db>.<table>` — column names and ClickHouse types
2. `SELECT count(*) FROM <db>.<table>` — total rows
3. Per column:
   - `SELECT uniq(<col>) FROM ...` — distinct value count (cardinality)
   - For numeric columns (Int*, UInt*, Float*, Decimal*): `SELECT min, max, avg`
   - For categorical columns with cardinality <= 100: `SELECT DISTINCT <col> LIMIT 5` — up to 5 sample values, each truncated at 64 characters

**PII protections:**
- Sample values capped at 5 per column
- Each sample value truncated at 64 characters (prevents long free-text blobs)
- Columns with >100 distinct values get "high-cardinality, no samples" instead of samples
- Only column names, types, and aggregate statistics reach the LLM prompt — no row-level free text for high-cardinality columns

### Column allow-list enforcement

The `validate_suggestions()` function in `app/ai/insights/suggestion_validator.py` builds an `allowed_columns` set from the profile's column names. Every column reference in a suggestion is checked against this set (case-insensitive). A single reference to a non-existent column causes the entire suggestion to be dropped (not just that field).

Specifically checked:
- `spec.query.query.dimensions[]` — each must be in allowed columns
- `spec.query.query.metrics[].column` — each (when not None) must be in allowed columns
- `spec.encoding.x` — must be in allowed columns (when not None)
- `spec.encoding.series[].field` — must match a metric alias defined in the query (cross-field consistency check, not an allow-list check per se)

---

## Prompt templates

| Template | Path | Variables |
|----------|------|-----------|
| `insights/v1/system.txt` | `backend/app/ai/prompts/insights/v1/system.txt` | `{result_set}` |
| `suggestions/v1/system.txt` | `backend/app/ai/prompts/suggestions/v1/system.txt` | `{dataset_profile}`, `{dataset_id}` |
| `suggestions/v1/user.txt` | `backend/app/ai/prompts/suggestions/v1/user.txt` | (none) |

Templates are loaded by `PromptLoader` (configured via `AI__PROMPT_TEMPLATE_DIR`). Model ID, temperature, and token limits all come from `AISettings` (env vars `AI__MODEL`, `AI__TEMPERATURE`, `AI__MAX_TOKENS`) — never hardcoded.

---

## Tenancy isolation

Both endpoints enforce tenancy strictly:

- The `TenantContext` is resolved from the authenticated JWT (`get_tenant_context`) — never from the request body.
- For `/ai/insights`: The result set is the caller's own already-computed dashboard data, so there is no data fetch. The main risk is hallucination (addressed by the guardrail), not cross-tenant data leakage. The tenant ID is logged with every gateway call.
- For `/ai/datasets/{dataset_id}/suggestions`: `DatasetService.get_for_tenant(ctx, dataset_id)` verifies ownership before any profiling or LLM call. A dataset not owned by the tenant returns 404 (same response as not-found, to prevent existence leaks).

---

## Module layout

```
backend/app/ai/insights/
    __init__.py              Public API / re-exports
    guardrail.py             No-invented-numbers pure function (verify_no_invented_numbers)
    summary.py               InsightService (sub-feature a)
    profiler.py              DatasetProfiler (PII-aware ClickHouse queries)
    suggestion_validator.py  Strict per-suggestion validation + column allow-list
    suggestions.py           SuggestionsService (sub-feature b)

backend/app/ai/prompts/
    insights/v1/system.txt   Existing insight template (injects {result_set})
    suggestions/v1/system.txt  New suggestions template
    suggestions/v1/user.txt    New suggestions user turn

backend/app/api/v1/ai.py     Two new endpoints added to the existing AI router

backend/tests/test_insights.py  57 tests across four parts
```
