# NL to SQL

> Phase 4, Task 4.3 -- grounded, validated, read-only NL->SQL endpoint.

`POST /api/v1/ai/query` translates a natural-language question into a SQL query,
validates it through a strict guardrail pipeline, executes it read-only against the
caller's tenant ClickHouse database, and returns the result.

This feature is **security-critical**.  The four-stage pattern from the
`nl-to-sql-grounding` skill is mandatory and non-negotiable.

---

## Architecture overview

```
POST /api/v1/ai/query
        |
        v
  TenantContext (resolved from JWT, never from request body)
        |
        v
  NLToSQLService.query()
        |
  +-----+-----+-----+-----+
  |     |     |     |
  v     v     v     v
Ground Gen  Validate Execute
```

### Stage 1 -- Ground

`SemanticLayerClient.meta(ctx)` calls `GET {CUBE__BASE_URL}/cubejs-api/v1/meta`
with a per-tenant HS256 JWT (the `clickhouse_db` claim comes from `ctx.clickhouse_db`
only -- never from the request).  The response lists the governed cubes, measures, and
dimensions for that tenant.

`build_grounding_context()` converts the meta response into:

- A compact **semantic text** block injected into the LLM system prompt.  Contains the
  **governed physical table name(s)** from `settings.serving_regional_sales_table`,
  measure/dimension column names derived from the Cube meta, and human-readable labels
  and descriptions.  The LLM is explicitly instructed to write SQL against the physical
  table name so the chain is consistent: grounding name == validator allow-list ==
  executed table.
- A `physical_tables` set on `GroundingContext` for reference/logging only.  The
  validator constructs its allow-list independently from
  `settings.serving_regional_sales_table` — see Stage 3.

### Stage 2 -- Generate

`LLMGateway.complete()` calls the configured LLM provider (set by `AI__PROVIDER` /
`AI__MODEL` -- never hardcoded) with the `nl_to_sql/v1` versioned prompt template.

The system prompt is rendered with:
- `{tenant_id}` -- the server-resolved tenant id.
- `{semantic_context}` -- the grounding text from stage 1.
- `{max_rows}` -- the deployment row cap from `settings.max_query_rows`.

The user prompt is rendered with `{question}`.

The LLM is instructed to emit exactly one read-only SELECT against the governed
objects listed in the semantic context, or the sentinel `UNSATISFIABLE` if the
question cannot be answered.

### Stage 3 -- Validate (before any execution)

`validate_and_cap()` in `app/ai/nl_sql/validator.py` parses the raw LLM output with
`sqlglot` (ClickHouse dialect) and applies the following guardrails **in order**:

| # | Guardrail | Rejection trigger |
|---|---|---|
| 1 | **UNSATISFIABLE sentinel** | LLM returned exactly `UNSATISFIABLE` |
| 2 | **Parse** | `sqlglot.parse()` fails (unparseable SQL) |
| 3 | **Single statement** | More than one statement; stacked queries |
| 4 | **Read-only** | Statement is not a `SELECT` (INSERT/UPDATE/DELETE/MERGE/ALTER/CREATE/DROP/TRUNCATE/CALL/etc.) |
| 5 | **TVF rejection** | Any `exp.Table` node whose `this` child is `exp.Anonymous` (i.e. a ClickHouse table-valued function: `url()`, `remote()`, `remoteSecure()`, `mysql()`, `postgresql()`, `s3()`, `cluster()`, `clusterAllReplicas()`, `merge()`, `file()`, etc.) — SSRF / exfiltration vectors |
| 5 | **Allow-list** | Any `Table` AST node with an empty/whitespace name OR a name not in the config-bound allow-list |
| 6 | **Tenant DB isolation** | Any `Table` AST node carries an explicit database qualifier that is NOT `ctx.clickhouse_db` |
| 7 | **Row cap + dangerous-clause strip** | No LIMIT → inject `LIMIT <max_query_rows>`; LIMIT > cap → clamp to cap; strip `SETTINGS`, `INTO OUTFILE`, and `FORMAT` clauses before regenerating SQL |

The AST walk covers ALL `exp.Table` nodes in the full parse tree including those nested
inside CTEs, subqueries, UNION arms, and JOIN clauses.

After guardrails 1-6 pass, SQL comments are stripped before the validated SQL string
is returned.

#### Why SETTINGS is stripped (not rejected)

A `SELECT ... SETTINGS max_execution_time=0` parses as a valid `SELECT` and passes the
read-only check because it contains no write/DDL.  However `SETTINGS` can disable
server-side timeout and memory limits, enabling a denial-of-service even under
`readonly=1`.  The SETTINGS clause is stripped silently from the AST so the query still
executes safely; the same logic applies to `INTO OUTFILE` and `FORMAT` clauses.

On **any** rejection a `SQLValidationError` is raised.  The caller (`NLToSQLService`)
never calls `run_read_only_query` when validation fails.

### Stage 4 -- Execute

`ClickHouseDatasetService.run_read_only_query(ctx, validated_sql)` runs the validated
SQL:
- Bound to `ctx.clickhouse_db` (the tenant's ClickHouse database -- cannot be
  overridden by the caller).
- With ClickHouse's `readonly=1` session setting enforced (defense in depth --
  read-only at the connection level even if the validator were somehow bypassed).

---

## Endpoint

```
POST /api/v1/ai/query
Authorization: Bearer <JWT>
Content-Type: application/json

{
  "question": "Which region had the highest total sales?"
}
```

**Success response (200)**

```json
{
  "sql":       "SELECT region, total_amount FROM serving_regional_sales ORDER BY total_amount DESC LIMIT 10000",
  "columns":   ["region", "total_amount"],
  "rows":      [["EMEA", 142500], ["APAC", 98300]],
  "row_count": 2
}
```

The `sql` field is the validated, row-capped SQL that was executed -- never the raw LLM
output.

**Validation failure (422)**

```json
{
  "detail": "Generated SQL references an object ('secrets') that is not in the governed semantic layer. Please rephrase using only the available metrics and dimensions."
}
```

All 422 messages are safe to display to the user.  They never include raw SQL, DB
internals, or provider error details.

**Provider/infrastructure unavailable (503)**

```json
{
  "detail": "AI provider is temporarily unavailable. Please try again."
}
```

---

## Allow-list: how governed tables are determined

The validator's allow-list is sourced **exclusively** from:

1. `settings.serving_regional_sales_table` (env: `SERVING_REGIONAL_SALES_TABLE`,
   default `serving_regional_sales`) -- the deployment config.  Same env var
   that Dagster and Cube consume, so there is one source of truth.

The allow-list is **NOT** widened by Cube annotations (`sql_table`, `sql` fields in
the `/meta` response).  A compromised or misconfigured Cube instance cannot expand the
set of physical tables reachable via NL→SQL.  The `sql` field on a Cube cube is an
arbitrary SQL fragment and is never treated as a table name.

The allow-list is compared **case-insensitively** against unqualified table names in
the SQL AST.  Any table name that is empty, whitespace-only, or not on the list is
rejected.  Table-valued functions (which produce nameless `exp.Table` nodes in the AST)
are also unconditionally rejected by a separate guard before the allow-list check.

---

## Tenant isolation guarantees

- The tenant context is resolved from the authenticated JWT at the API boundary
  (`get_tenant_context`).  The request body cannot influence it.
- The Cube meta JWT's `clickhouse_db` claim is set exclusively from
  `ctx.clickhouse_db`.
- The ClickHouse connection is opened bound to `ctx.clickhouse_db` -- unqualified
  table references cannot resolve outside the tenant database.
- Cross-tenant DB qualifiers (`other_tenant_db.table`) are explicitly rejected by
  the validator (guardrail 6), not just by the connection default.
- No tenant's meta response, prompt content, or query result is shared with or
  visible to another tenant.

---

## Configuration

All config comes from environment variables; nothing is hardcoded.

| Env var | Type | Default | Purpose |
|---|---|---|---|
| `SERVING_REGIONAL_SALES_TABLE` | str | `serving_regional_sales` | Physical name of the serving table in the validator allow-list. Same var Dagster/Cube use. |
| `AI__MODEL`, `AI__PROVIDER`, `AI__API_KEY` | str/secret | -- | LLM gateway config (see `docs/AI_GATEWAY.md`) |
| `AI__TEMPERATURE`, `AI__MAX_TOKENS` | float/int | 0.0/1024 | Generation params |
| `AI__PROMPT_TEMPLATE_DIR` | str | -- | Root directory for versioned prompt templates |
| `MAX_QUERY_ROWS` | int | 100000 | Hard cap injected/clamped into the LIMIT clause |
| `CUBE__BASE_URL`, `CUBE__API_SECRET` | str/secret | -- | Cube semantic layer connection |

Adding or changing `SERVING_REGIONAL_SALES_TABLE` requires a three-file change:
settings model, `.env.example`, and this docs page (see `config-management` skill).

---

## File layout

```
backend/app/ai/
  nl_sql/
    __init__.py         -- public re-exports
    grounding.py        -- Stage 1: build_grounding_context() from Cube meta
    validator.py        -- Stage 3: validate_and_cap() (the security chokepoint)
    service.py          -- NLToSQLService: orchestrates all 4 stages
  semantic/
    client.py           -- SemanticLayerClient.meta() added (Stage 1 data source)
  prompts/
    nl_to_sql/v1/
      system.txt        -- system-role prompt (injects {semantic_context})
      user.txt          -- user-turn template ({question})

backend/app/api/v1/
  ai.py                 -- POST /ai/query router

backend/tests/
  test_nl_to_sql.py     -- 37 tests (all mocked; no real network/LLM calls)
```

---

## Testing

All tests in `backend/tests/test_nl_to_sql.py` run fully in-process; the LLM gateway,
Cube semantic layer, and ClickHouse runner are all mocked.

| Criterion | Test(s) |
|---|---|
| (a) Valid question -> rows returned | `test_valid_question_returns_rows`, `test_valid_sql_without_limit_gets_limit_injected`, `test_valid_sql_with_excessive_limit_is_clamped`, `test_qualified_table_with_correct_tenant_db_is_accepted` |
| (b) Write/DDL rejected; execute never called | `test_delete_statement_is_rejected`, `test_update_statement_is_rejected`, `test_drop_statement_is_rejected`, `test_insert_statement_is_rejected`, `test_create_table_is_rejected` |
| (c) Off-semantic-layer table rejected | `test_unlisted_table_is_rejected`, `test_system_table_is_rejected`, `test_mixed_allowed_and_disallowed_table_is_rejected` |
| (d) Cross-tenant DB qualifier rejected | `test_cross_tenant_db_qualifier_is_rejected`, `test_cross_tenant_db_qualifier_direct_validator` |
| (e) Multi-statement rejected | `test_multi_statement_is_rejected`, `test_multi_statement_direct_validator` |
| (f) UNSATISFIABLE sentinel | `test_unsatisfiable_sentinel_raises_validation_error`, `test_unsatisfiable_direct_validator` |
| (g) meta() JWT + endpoint | `test_meta_calls_correct_endpoint`, `test_meta_carries_tenant_scoped_jwt`, `test_meta_raises_cube_auth_error_on_403` |
| (h) Grounding context | `test_grounding_context_*` (7 tests including FIX 3 tests) |
| (i) Settings allow-list env var | `test_settings_serving_regional_sales_table_default`, `test_settings_serving_regional_sales_table_from_env` |
| (j) Two-tenant isolation | `test_two_tenants_independent_grounding` |
| (k) Execute never called on failure | `test_execute_never_called_after_validation_failure` |
| FIX 1 — TVF rejection | `test_tvf_is_rejected_directly` (5 parametrized), `test_tvf_rejected_via_service_execute_never_called` (5 parametrized) |
| FIX 2 — SETTINGS strip | `test_settings_clause_is_stripped_from_output`, `test_settings_max_memory_stripped` |
