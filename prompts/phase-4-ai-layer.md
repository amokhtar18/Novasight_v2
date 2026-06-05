# Phase 4 — The AI layer

Goal: natural-language and insight features, grounded and safe. Every task follows the
nl-to-sql-grounding skill.

---

## Task 4.1 — Semantic layer
```
Use the data-engineer + ai-engineer.
Stand up the semantic layer (Cube or dbt MetricFlow) over the Phase 2/3 marts: define
metrics, dimensions, and join paths once. Expose a tenant-scoped query API the AI layer
will target. Connection + model config via settings.
Acceptance: a metric query returns correct numbers through the semantic layer for a
given tenant.
```

## Task 4.2 — LLM gateway abstraction
```
Use the ai-engineer. Follow config-management.
Build app/ai/gateway: a provider-agnostic interface. Model id, temperature, token
limits, and provider keys come from settings — none hardcoded. Support per-tenant model
selection. Add prompt templates as versioned files loaded from config.
Acceptance: switching the model via env changes behavior with no code change; keys never
appear in code/logs.
```

## Task 4.3 — NL→SQL (grounded + validated)
```
Use the ai-engineer. Follow nl-to-sql-grounding strictly.
Implement POST /v1/ai/query: ground on the semantic layer for the current tenant,
generate via the gateway, validate (sqlglot: single read-only statement, allow-listed
objects, row cap), execute on a read-only tenant-scoped connection, return rows.
Acceptance: a question returns correct data; a generated write/DDL is rejected; an
off-semantic-layer table is rejected.
```

## Task 4.4 — NL→chart
```
Use the ai-engineer + frontend-engineer.
Implement POST /v1/ai/chart that returns a validated chart-spec (same schema as Phase 3)
for a natural-language request, rendered by the existing renderer. Add a "describe your
chart" input in the UI.
Acceptance: a prompt produces a rendered chart; invalid specs are rejected, with a
graceful fallback to the manual builder.
```

## Task 4.5 — Automated insights & suggestions
```
Use the ai-engineer.
Add (a) dashboard insight summaries generated from already-computed result sets (no
invented numbers), and (b) source-based suggestions that profile a newly connected
dataset and propose metrics/charts.
Acceptance: summaries reflect real data; suggestions appear on connecting a dataset.
```

## Task 4.6 — Guardrail tests + review
```
Use the test-engineer, then reviewer.
Cover: read-only enforcement, allow-list enforcement, chart-spec rejection, and
no-cross-tenant-leak. Run /review-changes.
Acceptance: guardrail tests green; reviewer APPROVED.
```
