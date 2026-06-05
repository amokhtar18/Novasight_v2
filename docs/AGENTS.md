# Agents & skills

How the AI team is organized and when to use each member. Agents are *who*; skills are
the *rules* they follow.

## Agents (`.claude/agents/`)

| Agent | Model | Use it for | Tools |
|---|---|---|---|
| `orchestrator` | opus | Planning any multi-step task; breaking work into small ordered subtasks and routing to specialists. Does not write code. | read-only |
| `backend-engineer` | sonnet | FastAPI, control plane, tenancy, config, workers, DB models/migrations. | read/write/bash |
| `frontend-engineer` | sonnet | React UI, ECharts renderer, dnd-kit builder, exploration, API integration. | read/write/bash |
| `data-engineer` | sonnet | dlt ingestion, Iceberg, dbt models/tests, Dagster assets/checks, ClickHouse loads. | read/write/bash |
| `ai-engineer` | sonnet | NL→SQL, NL→chart, insights, suggestions, semantic layer, LLM gateway. | read/write/bash |
| `test-engineer` | haiku | Tests for any layer; prioritizes tenant-isolation and AI-guardrail tests. | read/write/bash |
| `reviewer` | sonnet | Final read-only audit before "done" against the golden rules, security, DoD. | read-only |

**Typical flow:** `orchestrator` plans → the right engineer implements → `test-engineer`
covers → `reviewer` approves. You can also call an engineer directly for a small task.

Model routing rationale: Opus for coordination/judgment, Sonnet for implementation,
Haiku for cheap high-volume work (search/tests). Override per agent in its frontmatter,
or globally via `CLAUDE_CODE_SUBAGENT_MODEL` (set in `.claude/settings.json`).

## Skills (`.claude/skills/`)

Rulebooks (auto-apply by context):

| Skill | Applies when… | Enforces |
|---|---|---|
| `config-management` | any code references a host/port/url/credential/path/model/threshold/flag | nothing environment- or tenant-specific is hardcoded; all config via one typed settings object |
| `tenancy-isolation` | any code reads/writes data, resolves storage, builds queries, runs pipelines, handles auth | tenant context resolved at the boundary, never from the client; data scoped per tenant; fail closed |
| `fastapi-conventions` | creating routers/services/deps/schemas/workers in `backend/app/` | module layout, DI, typed schemas, async, migrations, thin routers |
| `dbt-dagster-workflow` | editing dbt models/tests or Dagster assets in `data-platform/` | raw→staging→marts layering, quality gates as asset checks, per-tenant scoping |
| `nl-to-sql-grounding` | anything in `backend/app/ai/` | ground on semantic layer → generate via gateway → validate (read-only/allow-list/schema) → execute sandboxed; strict tenant scoping |

Actions (invoked as `/command`):

| Command | Does |
|---|---|
| `/scaffold-endpoint <name>` | Creates a tenant-scoped router + schema + service + tests following all skills. |
| `/review-changes [path]` | Runs the standard pre-done audit on the current diff via the reviewer. |

## Conventions for editing this team
- Keep agent `tools` minimal (least privilege). Reviewers and the orchestrator are
  read-only by design.
- Put durable rules in skills, not in prompts; put the next actions in `prompts/`.
- Skill `description` fields are how Claude decides to auto-apply them — keep them
  precise. Front-load the key trigger.
