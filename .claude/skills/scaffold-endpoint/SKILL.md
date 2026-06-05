---
name: scaffold-endpoint
description: >
  Scaffold a new tenant-scoped FastAPI resource (router + schemas + service + tests)
  following project conventions. Invoke as /scaffold-endpoint <resource-name>.
allowed-tools: Read, Write, Edit, Bash, Grep, Glob
---

Scaffold a new API resource named **$ARGUMENTS** for the Analytica backend.

Follow the `fastapi-conventions`, `tenancy-isolation`, and `config-management` skills.
Create, in `backend/app/`:

1. `schemas/$ARGUMENTS.py` — `Create`, `Update`, and `Read` Pydantic models.
2. `services/$ARGUMENTS.py` — a service class with CRUD methods that take
   `TenantContext` as the first argument and derive all scoping from it.
3. `api/v1/$ARGUMENTS.py` — a thin `APIRouter` that injects `get_tenant_context` and
   the service via `Depends`, delegates to the service, and returns `Read` models.
4. Register the router in the v1 app.
5. `tests/api/test_$ARGUMENTS.py` — happy path, validation error, auth failure, and a
   **tenant-isolation test** proving tenant A cannot access tenant B's records.

Rules:
- No hardcoded config; any new value goes to settings + `.env.example` +
  `docs/CONFIGURATION.md`.
- Tenant id comes only from the authenticated context, never the request body.

When done, run `uv run ruff check . && uv run mypy app && uv run pytest -q` and report
results, then hand off to the `reviewer` agent.
