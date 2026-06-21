# Staged prompts

This is the build backlog, broken into **small, ordered tasks**. Each task is a
self-contained prompt you paste into Claude Code, one at a time.

## How to use
1. Open the phase file. Work tasks **in order**.
2. Copy one task's prompt block into Claude Code.
3. Let the `orchestrator` plan if the task is multi-step; otherwise the named agent
   runs it directly.
4. A task is **done** only when: code works, tests pass (incl. a tenant-isolation test
   where data is touched), `ruff`/`mypy` or `tsc`/`eslint` are clean, and the relevant
   `docs/` page is updated.
5. Run `/review-changes` before committing. Commit per task with a clear message.

## Conventions in the prompts
- "Use the X agent" = delegate to that subagent.
- "Follow the Y skill" = that skill's rules are mandatory for the task.
- Acceptance criteria are listed so you (and the reviewer) know when it's done.

## Phase map
- `phase-0-foundations.md` — repo, compose, config, auth, tenant context
- `phase-1-vertical-slice.md` — CSV → Iceberg → ClickHouse → one chart (one tenant)
- `phase-2-transform-orchestrate.md` — dbt + Dagster + first quality gate
- `phase-3-visualization.md` — dashboards + low-code drag-and-drop builder
- `phase-4-ai-layer.md` — semantic layer, NL→SQL, NL→chart, insights
- `phase-5-reporting-governance.md` — Excel reports, alerts, catalog, encryption
- `phase-6-scale-out.md` — Helm/K8s, cloud multi-tenant, UX polish
- `phase-7-fine-tuning.md` — ingest hub, M:N schedules, dbt views + lineage, semantic
  wizard v2, charts/dashboards v2, unified AI assistant + agent framework

Golden rule reminder: **never hardcode configuration in the backend.** Every task that
introduces a config value must add it to settings + `.env.example` + `docs/CONFIGURATION.md`.
