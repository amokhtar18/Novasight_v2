# NL to Chart

> Phase 4, Task 4.4 — grounded, validated NL→Chart endpoint.

`POST /api/v1/ai/chart` translates a natural-language chart request into a validated
`ChartSpec` plus the resolved data, so the existing `ChartRenderer` in the frontend can
draw it without any transformation.

This feature is **security-critical**.  The four-stage pattern from the
`nl-to-sql-grounding` skill is mandatory and non-negotiable.

---

## Architecture overview

```
POST /api/v1/ai/chart
        |
        v
  TenantContext (resolved from JWT, never from request body)
        |
        v
  NLToChartService.generate()
        |
  +-----+-----+-----+-------+
  |     |     |     |
  v     v     v     v
Ground Gen  Validate Resolve
```

### Stage 1 — Ground

`SemanticLayerClient.meta(ctx)` calls `GET {CUBE__BASE_URL}/cubejs-api/v1/meta`
with a per-tenant HS256 JWT (the `clickhouse_db` claim comes from `ctx.clickhouse_db`
only — never from the request).  The response lists the governed cubes, measures, and
dimensions for that tenant.

`build_chart_grounding_context()` converts the meta response into:

- A compact **semantic text** block injected into the LLM system prompt.  Contains
  fully-qualified governed metric and dimension identifiers (e.g.
  `regional_sales.total_amount`, `regional_sales.region`) with titles and
  descriptions.  Physical table names are intentionally NOT surfaced — the LLM works
  entirely with governed semantic identifiers.
- An `allowed_metrics` set of fully-qualified measure names for the grounding
  allow-list check in Stage 3.
- An `allowed_dimensions` set of fully-qualified dimension names for the same
  allow-list check.

### Stage 2 — Generate

`LLMGateway.complete()` calls the configured LLM provider (set by `AI__PROVIDER` /
`AI__MODEL` — never hardcoded) with the `nl_to_chart/v1` versioned prompt template.

The system prompt is rendered with:
- `{tenant_id}` — the server-resolved tenant id.
- `{semantic_context}` — the grounding text from stage 1.

The user prompt is rendered with `{request}`.

The LLM is instructed to emit a single JSON `ChartSpec` object using only the governed
metric names in `metric_refs`, a governed dimension for `encoding.x`, and a sensible
chart `type`.  Or the sentinel `UNSATISFIABLE` if the request cannot be satisfied.

### Stage 3 — Validate (before any data resolution)

`validate_chart_spec()` in `app/ai/nl_chart/validator.py` applies the following
guardrails **in order**:

| # | Guardrail | Rejection trigger |
|---|---|---|
| 1 | **UNSATISFIABLE sentinel** | LLM returned exactly `UNSATISFIABLE` |
| 2 | **JSON parse** | LLM output is not valid JSON |
| 3 | **JSON object** | Parsed JSON is not a dict (e.g. an array) |
| 4 | **Strict schema validation** | Output fails `ChartSpec` validation in `extra="forbid"` mode: unknown/extra fields, wrong `type`, empty `series`, missing `x` for axis chart, invalid `FieldName` pattern |
| 5 | **AI-path gate (inline query)** | Spec has an inline `query.query` (AI path must use `metric_refs` only) |
| 6 | **AI-path gate (dataset_id)** | Spec has a `query.dataset_id` — the AI path is `metric_refs` only; a dataset_id would otherwise survive into the returned spec, pointing at a (possibly other-tenant) dataset record |
| 7 | **metric_refs present** | `query.metric_refs` is empty |
| 8 | **Grounding allow-list — metrics** | Any `metric_refs` entry or `series[].field` is not in `allowed_metrics` (the Cube meta for this tenant) |
| 9 | **series ⊆ metric_refs** | A `series[].field` is grounded but not listed in `metric_refs`, so it would be sent no measure and resolve to null data |
| 10 | **Grounding allow-list — dimensions** | `encoding.x` (when set) is not in `allowed_dimensions` |

The grounding allow-list (guardrails 8 and 10) is the hard tenant-safety gate.  Any
metric or dimension the LLM invented that does not appear in the governed Cube meta
for the current tenant is rejected before any data query is issued.

After all guardrails pass, a canonical `ChartSpec` (the shared contract — not the
internal strict subclass) is returned.

#### Strict-mode parsing without mutating the shared contract

`ChartSpec` in `app/schemas/chart.py` is the shared backend↔frontend contract and
must not be changed.  Strict-field enforcement is applied in this module by building
temporary `extra="forbid"` subclasses (`_StrictChartSpec`, etc.) used only for
AI-output parsing.  The canonical `ChartSpec` and its round-trip behaviour are
completely untouched.

### Stage 4 — Resolve data

`SemanticLayerClient.query(ctx, measures=..., dimensions=...)` executes the chart
metric query scoped to the current tenant:

- `measures` = `spec.query.metric_refs` (governed measure names)
- `dimensions` = `[spec.encoding.x]` if `encoding.x` is set, else `[]` for table
  charts

The returned `CubeRow` list is transformed into a `QueryResponse` whose `columns`
are `[encoding.x] + [s.field for s in encoding.series]` — exactly the field
references the frontend `ChartRenderer` uses to map columns to visual channels.
`Decimal` measure values are cast to `float` for safe JSON serialisation.

**Fail-closed:** on any generation/JSON-parse/validation/grounding failure, a
`ChartValidationError` is raised.  The endpoint maps this to a 422 with a safe,
user-friendly message.  `SemanticLayerClient.query` is NEVER called when validation
fails.

---

## Response contract: `{spec, data}`

The endpoint returns `NLChartResponse`:

```json
{
  "spec": {
    "version": "1",
    "type": "bar",
    "query": {
      "dataset_id": null,
      "query": null,
      "metric_refs": ["regional_sales.total_amount"]
    },
    "encoding": {
      "x": "regional_sales.region",
      "series": [
        {"field": "regional_sales.total_amount", "name": "Total Amount", "color": null}
      ]
    },
    "options": {
      "title": "Sales by Region",
      "stacked": false,
      "show_legend": true,
      "x_axis_label": null,
      "y_axis_label": null
    }
  },
  "data": {
    "columns": ["regional_sales.region", "regional_sales.total_amount"],
    "rows": [
      ["EMEA", 142500.0],
      ["APAC", 98300.0]
    ],
    "row_count": 2
  }
}
```

The `spec` field is a `ChartSpec` — the exact same schema as the manual chart builder.
The `data.columns` list is always `[encoding.x] + [s.field for s in encoding.series]`,
so the `ChartRenderer` can resolve `columns[0]` → x-axis values and each subsequent
column → a series by matching `series[i].field`.

**Python types:**
- `spec`: `app.schemas.chart.ChartSpec`
- `data`: `app.schemas.query.QueryResponse`
- Response model: `app.api.v1.ai.NLChartResponse`

---

## Endpoint

```
POST /api/v1/ai/chart
Authorization: Bearer <JWT>
Content-Type: application/json

{
  "request": "Show total sales by region as a bar chart"
}
```

**Success response (200)** — `NLChartResponse` as shown above.

**Validation failure (422)**

```json
{
  "detail": "The generated chart references metric 'regional_sales.invented' which is not in the governed semantic layer for this tenant. Please rephrase using only the available metrics."
}
```

All 422 messages are safe to display to the user.  They never include raw LLM output,
internal schema details, or provider error information.

**Provider/infrastructure unavailable (503)**

```json
{
  "detail": "AI provider is temporarily unavailable. Please try again."
}
```

---

## Grounding allow-list: how it works

The allow-list is populated exclusively from `SemanticLayerClient.meta(ctx)` for the
current tenant.  The measures extracted become `allowed_metrics`; the dimensions become
`allowed_dimensions`.  No config tables, no extra whitelist.

In `validate_chart_spec()`:

1. Every entry in `spec.query.metric_refs` is checked against `allowed_metrics`
   (case-insensitive).
2. Every `spec.encoding.series[].field` is checked against `allowed_metrics`.
3. `spec.encoding.x` (when present) is checked against `allowed_dimensions`.

If any check fails, a `ChartValidationError` is raised immediately and
`SemanticLayerClient.query` is never called.  A compromised or misconfigured Cube
instance that returns extra objects in the meta response can only widen what metrics
and dimensions the LLM can reference — it cannot widen the physical tables accessible
(those are governed by the NL→SQL path, not this path).

---

## Tenant isolation guarantees

- The tenant context is resolved from the authenticated JWT at the API boundary
  (`get_tenant_context`).  The request body cannot influence it.
- The Cube meta JWT's `clickhouse_db` claim is set exclusively from
  `ctx.clickhouse_db` — never from the request body.
- The Cube query JWT is minted the same way; the tenant cannot override the
  `clickhouse_db` claim.
- The grounding allow-list is computed from the current tenant's Cube meta response.
  No tenant's allowed metrics or dimensions cross into another tenant's grounding
  context.
- No tenant's meta response, prompt content, or query result is shared with or
  visible to another tenant.

---

## Configuration

All config comes from environment variables; nothing is hardcoded.

| Env var | Type | Default | Purpose |
|---|---|---|---|
| `AI__MODEL`, `AI__PROVIDER`, `AI__API_KEY` | str/secret | — | LLM gateway config (see `docs/AI_GATEWAY.md`) |
| `AI__TEMPERATURE`, `AI__MAX_TOKENS` | float/int | 0.0/1024 | Generation params |
| `AI__PROMPT_TEMPLATE_DIR` | str | — | Root directory for versioned prompt templates |
| `CUBE__BASE_URL`, `CUBE__API_SECRET` | str/secret | — | Cube semantic layer connection |

No additional settings are needed for the chart path beyond what NL→SQL already requires.

---

## File layout

```
backend/app/ai/
  nl_chart/
    __init__.py         — public re-exports
    grounding.py        — Stage 1: build_chart_grounding_context() from Cube meta
    validator.py        — Stage 3: validate_chart_spec() (the security chokepoint)
    service.py          — NLToChartService: orchestrates all 4 stages
  prompts/
    nl_to_chart/v1/
      system.txt        — system-role prompt (injects {semantic_context})
      user.txt          — user-turn template ({request})

backend/app/api/v1/
  ai.py                 — POST /ai/chart added to the existing router

backend/tests/
  test_nl_to_chart.py   — 42 tests (all mocked; no real network/LLM calls)
```

---

## Testing

All tests in `backend/tests/test_nl_to_chart.py` run fully in-process; the LLM
gateway, Cube meta, and Cube query are all mocked.

| Criterion | Test(s) |
|---|---|
| (a) Valid prompt → spec + data | `test_valid_request_returns_spec_and_data`, `test_spec_version_is_preserved`, `test_decimal_values_cast_to_float`, `test_line_chart_type_is_accepted`, `test_table_chart_with_no_x_is_accepted`, `test_multiple_metrics_in_spec` |
| (b) Invalid spec rejected; query never called | `test_malformed_json_is_rejected`, `test_unknown_extra_field_is_rejected`, `test_invalid_chart_type_is_rejected`, `test_missing_series_is_rejected`, `test_missing_x_for_axis_chart_is_rejected`, `test_inline_query_is_rejected`, `test_unsatisfiable_sentinel_is_rejected`, `test_json_non_object_is_rejected` |
| (c) Ungrounded metric/dimension rejected; query never called | `test_ungrounded_metric_ref_is_rejected`, `test_ungrounded_series_field_is_rejected`, `test_ungrounded_dimension_x_is_rejected`, `test_empty_meta_rejects_any_spec` |
| (d) No cross-tenant: tenant from server only | `test_meta_called_with_server_resolved_tenant_context`, `test_query_called_with_server_resolved_tenant_context`, `test_two_tenants_have_independent_meta_calls` |
| Direct validator unit tests | `test_direct_validator_*` (8 tests) |
| Grounding context unit tests | `test_grounding_*` (6 tests) |
| query never called on any rejection | `test_query_never_called_on_rejection` (7 parametrized) |
