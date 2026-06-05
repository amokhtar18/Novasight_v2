# CLAUDE.md — Analytica project memory

> This file is **always** in Claude Code's context. Keep it short and high-signal.
> Detailed material lives in `docs/` and is loaded on demand.

## What we are building

Analytica is a managed, low-code data analytics & BI platform. It scales from a
single-server on-prem (single-tenant) install to a cloud-native multi-tenant SaaS,
**from the same codebase**. The only things that change between deployments are
configuration and the storage backends behind an S3-compatible seam.

Read `docs/ARCHITECTURE.md` before designing anything new.

## The five golden rules (non-negotiable)

1. **No hardcoded configuration in the backend — ever.** Every URL, port, credential,
   bucket, model name, feature flag, threshold, or path comes from settings loaded
   from the environment. See the `config-management` skill. Code reviews must reject
   any literal that is environment- or tenant-specific.
2. **Tenancy is a cross-cutting invariant.** Every data-touching code path resolves a
   tenant context at the boundary and uses it to scope storage prefix, ClickHouse
   database, and dbt schema. Never trust a tenant id from the client body. See the
   `tenancy-isolation` skill. On-prem this collapses to a single tenant, but the code
   path is identical.
3. **AI-generated SQL is read-only, grounded, and validated.** The AI layer queries the
   semantic layer, never raw physical tables, and every generated query is validated
   and sandboxed before execution. See the `nl-to-sql-grounding` skill.
4. **Ship thin vertical slices.** Prove an end-to-end path before adding breadth.
   Do not gold-plate one layer in isolation.
5. **Definition of done = tested + typed + documented.** New code has tests, passes
   `ruff` + `mypy` (backend) / `tsc` + `eslint` (frontend), and updates the relevant
   `docs/` page. No exceptions.

## Tech stack (pin to current stable when you reach each layer)

Backend: Python 3.12, FastAPI (async), Pydantic v2 + pydantic-settings, SQLAlchemy 2.0,
Alembic, Dramatiq/Redis, dlt, clickhouse-connect.
Data: Apache Iceberg + REST catalog (Polaris/Nessie), MinIO/S3, dbt Core, Dagster.
Serving: ClickHouse. Semantic layer: Cube (or dbt MetricFlow).
Frontend: React + TypeScript + Vite, shadcn/ui + Tailwind, ECharts, dnd-kit,
Zustand, TanStack Query.
Infra: Docker Compose (dev/on-prem), Helm/K8s (cloud), Prometheus + Grafana + OTel.

## Repo layout

```
backend/app/{api,core,tenancy,ingestion,ai,reporting}   # FastAPI modular monolith
frontend/                                                # React app + low-code builder
data-platform/{orchestration,dbt}                        # Dagster + dbt
infra/{compose,helm}                                     # deployment
docs/                                                    # architecture & guides
prompts/                                                 # staged, copy-paste task prompts
.claude/{agents,skills,settings.json}                    # this framework
```

## How to work in this repo

- **Agents** (`.claude/agents/`) are specialists. Delegate to them by role; the
  `orchestrator` plans and routes. See `docs/AGENTS.md`.
- **Skills** (`.claude/skills/`) are the rulebooks + reusable actions. They auto-apply
  by context; some are invoked as `/command`.
- **Prompts** (`prompts/phase-*.md`) are the staged backlog — small, ordered tasks.
  Paste one task at a time; finish it to "done" before the next.
- Always start a task by reading the relevant skill, then the relevant `docs/` page.

## Quick commands

- Backend tests/lint: `cd backend && uv run pytest && uv run ruff check . && uv run mypy app`
- Frontend: `cd frontend && pnpm test && pnpm exec tsc --noEmit && pnpm lint`
- Local stack up: `docker compose -f infra/compose/docker-compose.yml up -d`
