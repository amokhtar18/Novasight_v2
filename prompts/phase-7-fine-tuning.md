# Phase 7 — Fine-tuning & feature widening

A cross-cutting fine-tuning pass over the existing surfaces: reorganise ingest,
deepen modelling/transform UX, broaden charts & dashboards, and unify the AI layer
behind a reusable agent framework. **Status: all 13 items delivered, tested, and
deployed to the dev stack** (this file is the record of the plan + decisions).

> Golden rules still apply: no hardcoded backend config; tenancy resolved at the
> boundary; AI is grounded/validated/read-only; thin vertical slices; done = tested +
> typed + documented.

## Locked decisions (asked & answered before building)

1. **AI autonomy** — *propose-then-confirm*: the assistant generates charts /
   dashboards / insight summaries inline; nothing is persisted until the user acts.
2. **Charts source** — *semantic models only*; the CSV/dataset path is removed from the
   builder. CSV remains an ingestion on-ramp (upload → model → chart).
3. **Semantic member SQL** — *validated expression grammar*: window/string/CASE etc.
   allowed via an allow-list validator; column dropdowns from the introspected mart
   schema. (Author-written, validated — a different trust boundary than AI-generated SQL.)
4. **Lineage** — parsed *in-app* from `{{ ref()/source() }}`; scope = dbt model→model + sources.
5. **Schedules** — *reusable, M:N*: one cron attached to many pipelines.
6. **Ingest IA** — one *Ingest hub* at `/pipelines` (Data sources | Pipelines | Schedules);
   `/data` retired into it.
7. **Dashboard tiles** — generalised with a `kind` discriminator: chart / text / markdown /
   image-by-URL / divider / filter.
8. **Sequencing** — dependency-aware phase order (below).

## Phase order & items

### Phase 0 — Verify the AI provider (de-risks all AI work)
- ✅ **#12 Test the AI API key** — `GET /ai/health` (superuser, soft-fails, key never
  leaked) + Settings → "Test connection". *Files:* `app/api/v1/ai.py`,
  `frontend/src/pages/Settings.tsx`. *Tests:* `tests/test_ai_health_api.py`.

### Phase A — Ingest hub & ops
- ✅ **#1 Data sources tab in Pipelines** — tabbed Ingest hub; `/data` → `/pipelines?tab=sources`.
  *Files:* `pages/Pipelines.tsx`, `components/data/DatasetsPanel.tsx`,
  `components/schedule/SchedulesPanel.tsx`, `App.tsx`, `nav.ts`.
- ✅ **#2 Recent-runs filters + duration** — status / pipeline / run-time window filters and
  a duration column on Operations. *Files:* `pages/Operations.tsx`, `lib/format.ts`.
- ✅ **#3 Reusable M:N schedules** — `schedule_pipelines` join table, fan-out dispatcher,
  central CRUD + multi-pipeline attach. *Migration:* `0010`. *Files:*
  `models/schedule_pipeline.py`, `services/schedules.py`, `schemas/schedule.py`,
  `components/schedule/SchedulesPanel.tsx`. *Tests:* `tests/test_schedules_api.py`.

### Phase B — Modelling & lineage
- ✅ **#4 dbt models view** — tiles⇄list toggle + search/layer/materialization/status filters.
  *Files:* `pages/DbtModels.tsx`.
- ✅ **#5 dbt lineage** — `GET /dbt-models/lineage` (parse `ref()/source()`), ECharts DAG.
  *Files:* `services/dbt_lineage.py`, `components/dbt/LineageView.tsx`.
  *Tests:* `tests/test_dbt_lineage.py`.
- ✅ **#6 Semantic wizard v2** — validated SQL-expression grammar (allow-list; rejects
  TVFs/subqueries/comments/qualified names), serving-table column dropdowns, multi-column
  joins. *Files:* `core/sql_expression.py`, `schemas/semantic_model.py`,
  `codegen/cube_model.py`, `services/serving.py` + `api/v1/serving.py`,
  `pages/SemanticModels.tsx`. *Tests:* `tests/test_sql_expression.py` (security),
  `tests/test_serving.py`, `tests/test_cube_codegen.py`.

### Phase C — Charts & dashboards
- ✅ **#8 Chart builder v2** — ChartSpec v2 (new types: hbar/combo/donut/funnel/treemap/
  radar/gauge; formatting: number format, legend, sort, data labels, axis bounds/log,
  palette), semantic-only builder + Format panel. *Files:* `schemas/chart.py`,
  `types/api.ts`, `components/chart/ChartRenderer.tsx`, `lib/chartFormat.ts`,
  `pages/Builder.tsx`. *Tests:* `tests/test_chart_spec.py`, `test/chartRenderer.test.ts`.
- ✅ **#9 Charts list** — `/charts` library with live previews + pin/delete.
  *Files:* `pages/Charts.tsx`.
- ✅ **#10 Dashboard wizard v2** — generalised tiles (`kind` + `content`, nullable `chart_id`),
  Add-object dialog, render text/markdown(safe)/image/divider/filter. *Migration:* `0011`.
  *Files:* `models/dashboard.py`, `schemas/dashboard.py`, `services/dashboards.py`,
  `components/dashboard/DashboardCardTile.tsx`, `pages/DashboardDetail.tsx`, `lib/markdown.ts`.

### Phase D — Unified AI assistant & framework
- ✅ **#13 Agent framework** — `app/ai/agent/` (Skill, SkillRegistry, Agent loop) +
  versioned prompt instructions (`prompts/assistant/v1/system.txt`). *Tests:*
  `tests/test_agent_runtime.py`.
- ✅ **#7 + #11 Unified Assistant** — `POST /ai/assistant` + `pages/Assistant.tsx` merging
  Chat + Insights + NL→SQL; propose-then-confirm (inline charts to save/pin, insight
  summaries, "Build dashboard" from the session). `/explore`, `/chat`, `/insights`
  redirect in; old pages removed. *Files:* `app/ai/assistant/`, `api/v1/ai.py`.

## Migrations
- `0010` — `schedule_pipelines` join table (+ backfill from `schedules.target_id`).
- `0011` — `dashboard_tiles.kind` + `content`, `chart_id` nullable (batch mode; SQLite-safe).

## Verification
- Backend: **752 pytest**, `ruff`/`mypy` clean. Frontend: **132 vitest**, `tsc`/`eslint` clean.
- Deployed to the local Compose stack (api + frontend rebuilt; `0010`+`0011` applied).

## Deferred / follow-ups
- More chart types needing richer encoding: heatmap, box plot, pivot, histogram,
  calendar/geo maps (the ChartSpec v2 contract is ready for them).
- Filter/slicer tile could pull distinct dimension values (currently a typed value).
- Legacy `/ai/chat` endpoint + `ChatService` remain (UI no longer uses them) — retire when convenient.
- Run the live AI key check (Settings → Test connection) against the deployed key.
