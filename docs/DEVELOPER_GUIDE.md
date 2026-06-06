# Developer guide

Welcome to NovaSight. This guide gets you productive and shows how to add features the
right way. Read `CLAUDE.md` (the always-on rules) and `ARCHITECTURE.md` first; this page
is the practical "how we work".

## 1. Mental model in one minute

NovaSight is a **modular monolith** that runs two ways from one codebase:
- **On-prem**: single server, single tenant, `docker compose up`, MinIO + local Postgres.
- **Cloud**: Kubernetes, multi-tenant, Helm, S3 + managed Postgres.

The only differences are **configuration** and the **storage backend behind the
S3-compatible seam**. Tenancy is pooled compute + isolated data (each tenant has its own
Iceberg namespace, ClickHouse database, and dbt schema). On-prem, that's one tenant.

Data flows: sources → ingestion (dlt) → Iceberg lake → dbt+Dagster transform → ClickHouse
serving → React viz. The AI layer sits beside it, grounded on a governed semantic layer.

## 2. This Claude Code framework

You build with a team of AI specialists, coordinated by you.

```
.claude/
  agents/   specialists you delegate to (orchestrator, backend/frontend/data/ai
            engineers, test-engineer, reviewer)
  skills/   the rulebooks (config-management, tenancy-isolation, fastapi-conventions,
            dbt-dagster-workflow, nl-to-sql-grounding) + actions (/scaffold-endpoint,
            /review-changes)
  settings.json  permissions + default models
CLAUDE.md   always-in-context project rules
prompts/    the staged backlog: small ordered tasks per phase
docs/       this guide + architecture + agents + configuration
```

- **Agents** = *who* does the work. Skills auto-apply by context; some run as `/command`.
- **Prompts** = *what* to do next, broken into small tasks. Work them in order.
- See `AGENTS.md` for each agent/skill and when to use it.

## 3. Day-one setup

```bash
git clone <repo> && cd novasight
docker compose -f infra/compose/docker-compose.yml up -d   # data services
cp .env.example .env                                       # fill in local values
cd backend && uv sync && uv run alembic upgrade head        # backend + schema
uv run python -m app.scripts.seed                           # bootstrap tenant (from settings)
cd ../frontend && pnpm install                              # frontend
```

> Migrations live in `backend/alembic/` and are settings-driven — there is no DB URL in
> `alembic.ini`; `env.py` reads it from `app.core.config`. The seed script provisions the
> single `SEED_TENANT__*` tenant (its Iceberg namespace / ClickHouse db / dbt schema are
> derived from the slug) and is idempotent, so it is safe to re-run.
Open the repo in VS Code, start Claude Code, and confirm it loaded `CLAUDE.md`
(`/context` shows it). Then open `prompts/phase-0-foundations.md` and start at Task 0.1.

## 4. The build loop (every task)

1. Pick the next task from the current `prompts/phase-*.md`.
2. Paste it into Claude Code. Multi-step? The `orchestrator` plans and routes; otherwise
   the named agent runs it.
3. The agent reads the relevant **skill** and **architecture** section, implements the
   smallest correct change, and adds tests (or hands to `test-engineer`).
4. Run quality gates locally (section 6).
5. Run `/review-changes`; fix anything the `reviewer` flags.
6. Commit with a message referencing the task (e.g. `feat(tenancy): task 0.5 tenant context`).

A task is **done** only at: working code + tests (incl. tenant-isolation where data is
touched) + clean lint/types + updated `docs/`.

## 5. How to add a new feature (the recipe)

> Example: "add a 'cohort retention' metric and a chart for it."

1. **Locate the layer(s).** Use `ARCHITECTURE.md`. A new metric touches the data plane
   (dbt mart + semantic layer) and possibly the AI layer (so NL can ask for it) and the
   frontend (a chart).
2. **Ask the orchestrator to plan** it into small subtasks with owners.
3. **Data**: `data-engineer` adds/extends the dbt mart with tests (`dbt-dagster-workflow`),
   then exposes the metric in the semantic layer.
4. **Backend**: if a new endpoint is needed, run `/scaffold-endpoint <name>` — it creates
   a tenant-scoped router + schema + service + tests following all skills.
5. **AI**: `ai-engineer` ensures the metric is reachable via NL through the semantic
   layer (`nl-to-sql-grounding`). No new raw-table access.
6. **Frontend**: `frontend-engineer` adds the chart using the shared chart-spec + renderer.
7. **Config**: any new value → settings + `.env.example` + `CONFIGURATION.md`. Never a literal.
8. **Tests + review**: `test-engineer` covers it (including isolation), then `reviewer`.
9. **Docs**: update the relevant `docs/` page and, if behavior changed, `CLAUDE.md`.

**The non-negotiables when adding anything:** no hardcoded config; tenant scope from the
authenticated context; AI stays read-only/validated/semantic-layer-only; tests + docs.

## 6. Quality gates

```bash
# Backend
cd backend && uv run ruff check . && uv run mypy app && uv run pytest -q
# Frontend
cd frontend && pnpm exec tsc --noEmit && pnpm lint && pnpm test
# Data
cd data-platform/dbt && dbt parse && dbt build --select <model>
```

## 7. Extending the framework itself

- **New recurring rule** → add/edit a skill in `.claude/skills/`. Keep the `description`
  precise so it auto-triggers on the right tasks; put the rules in the body.
- **New specialist** → add an agent in `.claude/agents/` with a tight `tools` list and a
  clear "Use PROACTIVELY when…" description; note it in `AGENTS.md`.
- **New reusable action** → a skill with `allowed-tools` and `$ARGUMENTS` (like
  `/scaffold-endpoint`).
- **New backlog work** → add tasks to the right `prompts/phase-*.md`, small and ordered,
  each naming the owner agent, the skills to follow, and acceptance criteria.
- Keep `CLAUDE.md` short — it's always in context. Detail belongs in `docs/` and skills.

## 8. Where things live (quick map)

| You want to… | Go to |
|---|---|
| Understand the system | `docs/ARCHITECTURE.md` |
| Know who does what | `docs/AGENTS.md` |
| Add/inspect a config value | `backend/app/core/config.py`, `.env.example`, `docs/CONFIGURATION.md` |
| Add an API resource | `/scaffold-endpoint`, then `backend/app/api`, `services`, `schemas` |
| Add tenant logic | `backend/app/tenancy/`, skill `tenancy-isolation` |
| Change the DB schema | add a model in `backend/app/models/`, then `uv run alembic revision --autogenerate` |
| Seed the bootstrap tenant | `uv run python -m app.scripts.seed` (reads `SEED_TENANT__*`) |
| Add a data model/metric | `data-platform/dbt`, skill `dbt-dagster-workflow` |
| Add an AI feature | `backend/app/ai/`, skill `nl-to-sql-grounding` |
| Add a chart/dashboard | `frontend/`, the chart-spec contract |
| Know what to build next | `prompts/phase-*.md` |
