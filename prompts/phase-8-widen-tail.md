# Phase 8 — Widen tail & finish-off

The clean-up backlog that consolidates every remaining item after Phases 0–7. These are
the "what's left" cells from the **refreshed** active-plan gap table
(`~/.claude/plans/abundant-floating-floyd.md`, refreshed 2026-07-04) plus the
`Deferred / follow-ups` from `phase-7-fine-tuning.md`. Unlike Phase 7, **nothing here is
built yet** — this is a forward backlog. Work tasks in order.

> Golden rules still apply: no hardcoded backend config (new values → `config.py` +
> `.env.example` + `docs/CONFIGURATION.md`); tenancy resolved at the boundary and never
> trusted from the client; AI is grounded/validated/read-only; thin vertical slices;
> done = tested + typed + documented. Run `/review-changes` and commit per task.

## Source of each task
| Task | Requirement | Origin |
|------|-------------|--------|
| 8.1 | #13 finish | Gap table — `environment` enum still includes `local` |
| 8.2 | #2 finish | Open item — RBAC viewer/editor depth |
| 8.3 | #3 widen | Active-plan decision "REST/SaaS deferred" |
| 8.4 | #9 widen | phase-7 deferred — richer chart types |
| 8.5 | #10 widen | phase-7 deferred — filter-tile distinct values |
| 8.6 | #12 cleanup | phase-7 deferred — retire legacy `/ai/chat` |
| 8.7 | ops | phase-7 deferred — live AI-key check |
| 8.8 | done gate | docs + review sweep |

---

## Task 8.1 — Collapse the `local` environment mode
```
Use the backend-engineer. Follow config-management.
The environment enum is still `local | onprem | cloud` (backend/app/core/config.py:445),
but the "local" deployment mode was retired in favour of the unified compose. Remove
`local` from the enum and audit every reader/branch that special-cases it (grep the
backend for `== "local"`, `"local"`, and environment-conditional logic). Fold any
still-needed dev behaviour into onprem defaults; delete dead local-only branches.
Acceptance: enum is `onprem | cloud` only; `ruff`+`mypy` clean; existing tests pass with
env set to onprem; no code path references a "local" environment; docs/CONFIGURATION.md
and docs/DEPLOYMENT.md updated.
```

## Task 8.2 — RBAC depth: viewer vs editor
```
Use the backend-engineer, then frontend-engineer. Follow tenancy-isolation.
Today only platform-admin + tenant `superuser` exist. Add tenant-scoped `viewer` and
`editor` roles and enforce them on write paths (charts, dashboards, sources, pipelines,
dbt/semantic models) via a role dependency mirroring the existing superuser/platform-admin
deps in security.py. Viewers get read-only; editors get CRUD but not scheduling. Surface
role in the user-management UI.
Acceptance: a viewer JWT is rejected (403) on every write endpoint with a tenant-isolation
+ role test per surface; editor can CRUD but not schedule; UI hides disallowed actions;
docs/AUTH.md updated with the role matrix.
```

## Task 8.3 — REST / SaaS connector
```
Use the data-engineer. Follow tenancy-isolation + config-management.
Extend ingestion/connectors/ with a REST/API connector (dlt rest_api source): config
schema (base URL, auth, pagination, resources), build_dlt_source(), test_connection(),
preview() — same contract as the sql_database + filesystem connectors. Credentials
encrypted at rest via core/crypto.py. Wire it into the Sources wizard.
Acceptance: a REST source can be created, tested, previewed, and run through a pipeline to
Iceberg→ClickHouse; connector-registry + tenant-isolation tests; docs/ETL.md updated.
```

## Task 8.4 — Richer chart types
```
Use the frontend-engineer, then test-engineer.
ChartSpec v2 is ready for encodings it doesn't yet render. Add heatmap, box plot, pivot
table, and histogram (geo/calendar maps optional, behind the same contract). Extend
schemas/chart.py validation + types/api.ts + components/chart/ChartRenderer.tsx and the
Builder type picker + Format panel. Keep one renderer for manual + AI + saved charts.
Acceptance: each new type renders from a semantic-model query and round-trips through
save/load; chart-spec (backend) + chartRenderer (frontend) tests cover each; docs/CHART_SPEC.md
+ docs/FRONTEND.md updated.
```

## Task 8.5 — Filter-tile distinct dimension values
```
Use the backend-engineer, then frontend-engineer.
The dashboard filter/slicer tile currently takes a typed literal. Add a read-only,
tenant-scoped endpoint that returns distinct values for a governed dimension (via the
semantic layer / serving path — never raw physical tables), and populate the filter tile
as a dropdown. Cache/limit results.
Acceptance: filter tile offers governed distinct values scoped to the tenant; tenant-isolation
test proves values don't leak across tenants; docs/DASHBOARDS.md updated.
```

## Task 8.6 — Retire the legacy chat surface
```
Use the ai-engineer. Follow nl-to-sql-grounding.
The unified Assistant replaced Chat, but the legacy /ai/chat endpoint + ChatService remain
shipped and unused by the UI. Remove them (and dead imports/tests), confirming no route,
MCP tool, or frontend call still depends on them.
Acceptance: /ai/chat + ChatService deleted; grep shows no live references; full backend
suite + ruff/mypy clean; docs/AI_GATEWAY.md / docs/MCP_SERVER.md reflect the single
Assistant surface.
```

## Task 8.7 — Live AI-key verification in the deployed stack
```
Use the ai-engineer. Follow config-management.
Exercise GET /ai/health (Settings → "Test connection") against the real deployed key on the
dev Compose stack; confirm it soft-fails cleanly and never leaks the key. Fix any wiring
gaps found. This is an ops-verification task, not new surface.
Acceptance: Settings → Test connection returns healthy against the deployed key; a failure
path (bad key) reports a safe error with no key material in logs/response; result noted in
docs/AI_GATEWAY.md.
```

## Task 8.8 — Docs + review sweep
```
Use the reviewer.
Re-run the full gate (backend pytest + ruff + mypy; frontend vitest + tsc + eslint) and
/review-changes across Phase 8. Confirm the active-plan gap table and this file reflect
reality; mark delivered items.
Acceptance: full gate green first-hand (not just focused tests); reviewer APPROVED; gap
table + Phase 8 statuses updated to "done".
```
