---
name: nl-to-sql-grounding
description: >
  The mandatory safety pattern for every AI feature in NovaSight (NL→SQL, NL→chart,
  insights, suggestions). Apply when writing or reviewing anything in backend/app/ai/.
  Enforces grounding on the governed semantic layer, read-only validated execution, and
  strict tenant scoping.
---

# NL→SQL grounding & guardrails

The LLM is powerful and confidently wrong. The semantic layer + validation make it
safe. Four stages, always, for every AI feature:

## 1. Ground (retrieve context)
- Pull context from the **governed semantic layer** (Cube / dbt MetricFlow): available
  metrics, dimensions, allowed join paths, descriptions — for the **current tenant
  only**.
- Optionally add catalog descriptions and a few sample values (tenant-scoped, PII-aware).
- The LLM **never** sees or targets raw physical tables. The semantic layer is the only
  surface it knows about.

## 2. Generate
- Call the LLM through the **gateway abstraction** (`app/ai/gateway`) so the provider
  and model are swappable per tenant/cost tier — model id, temperature, and token
  limits come from settings, never hardcoded.
- Use a **versioned prompt template** loaded from config, with the grounding context
  injected. Templates live in files, are versioned, and are reviewed.

## 3. Validate (before anything executes)
- **SQL**: parse it (e.g. `sqlglot`). Reject unless: single statement, `SELECT`/read
  only (no `INSERT/UPDATE/DELETE/DDL/CALL`), references only semantic-layer-backed
  objects on the allow-list, has a sane row/scan limit.
- **Chart spec**: validate against the chart-spec Pydantic/JSON schema; reject unknown
  fields.
- **Insights/summaries**: never invent numbers — summaries are produced from the
  already-computed result set, not free-form generation.

## 4. Execute / return
- Run validated SQL on a **read-only, tenant-scoped** ClickHouse connection in a
  sandbox with timeouts and row caps. Read-only is enforced at the connection level too
  (defense in depth).
- Return the validated chart spec to the frontend (shared renderer with manual charts).

## Hard rules
- No write/DDL ever reaches the database from generated SQL.
- No tenant's data, context, or cache entry crosses into another tenant.
- Log prompts and outputs with tenant tagging and PII/secret redaction.
- Always provide a graceful fallback when generation or validation fails (ask to
  rephrase / offer the manual query builder) — never execute unvalidated output.

## Test these paths
Read-only enforcement (a generated `DELETE`/`UPDATE`/DDL is rejected), allow-list
enforcement (off-semantic-layer table rejected), chart-spec schema rejection, and
no-cross-tenant-leak. These are required before "done".
